"""Candidate Pair Generation & Deduplication Service for SongNhat CRM.

Sub-milestone: P2.3.3 - Candidate Generation & Deduplication
Module: backend.matching.candidate_generator

Implements:
1. Candidate Pair Generation from multi-path blocking inverted indexes.
2. Scope Enforcement:
   - ACCOUNT: CRM_A within-source, CRM_B within-source, CRM_A cross CRM_B.
   - CONTACT: CRM_C within-source.
   - Strictly prohibits cross-pool (ACCOUNT vs CONTACT) and unauthorized systems.
3. Candidate Ceiling Enforcement:
   - Default ceiling = 200,000 pairs.
   - <= 200,000: Generation completes normally.
   - >= 200,001: Triggers ceiling_breached=True, status HELD_CEILING_BREACH, halts generation.
   - Zero silent top-K truncation.
4. Oversized Group Management (threshold 500):
   - Audits and tracks oversized groups without silent omission.
5. Idempotent Database Persistence:
   - Batched insertion into `candidate_pairs` and `candidate_blocking_paths`.
   - Transaction rollback on failure.
   - Conflict resolution for idempotent retries.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.matching.blocking_engine import (
    BlockingCandidatePair,
    BlockingPath,
    BlockingStrategy,
    MultiPathBlockingEngine,
    SourceRecordInput,
    EntityPool,
)
from backend.matching.pair_deduplicator import PairDeduplicator, DeduplicationStats
from backend.models.intake import MatchingRun, SourceRecord
from backend.models.matching import CandidatePair, CandidateBlockingPath

logger = logging.getLogger(__name__)


# Standard pool to source system mappings
POOL_SYSTEM_SCOPE: Dict[str, Set[str]] = {
    EntityPool.ACCOUNT.value: {"CRM_A", "CRM_B"},
    EntityPool.CONTACT.value: {"CRM_C"},
}


class CandidateGenerationStats(BaseModel):
    """Auditable statistics for candidate pair generation and deduplication."""

    matching_run_id: Optional[str] = None
    entity_pool: str = "ACCOUNT"
    records_received: int = 0
    records_in_scope: int = 0
    records_out_of_scope_filtered: int = 0
    blocking_groups_evaluated: int = 0
    oversized_groups_count: int = 0
    oversized_groups_details: List[Dict[str, Any]] = Field(default_factory=list)
    raw_pairs_generated: int = 0
    duplicate_pairs_pruned: int = 0
    unique_candidates_count: int = 0
    multi_path_candidates_count: int = 0
    ceiling_breached: bool = False
    ceiling_limit: int = 200_000
    run_status: str = "COMPLETED"  # "COMPLETED", "HELD_CEILING_BREACH", "FAILED"
    generation_time_seconds: float = 0.0
    persistence_time_seconds: float = 0.0
    deduplication_stats: Optional[DeduplicationStats] = None


class CandidateGenerationResult(BaseModel):
    """Complete result package of candidate generation."""

    matching_run_id: Optional[str] = None
    entity_pool: str
    candidate_pairs: List[BlockingCandidatePair] = Field(default_factory=list)
    stats: CandidateGenerationStats = Field(default_factory=CandidateGenerationStats)


class CandidateGenerator:
    """Orchestrates candidate generation, deduplication, and persistence."""

    def __init__(
        self,
        entity_pool: str = "ACCOUNT",
        candidate_ceiling: int = 200_000,
        max_group_size: int = 500,
        allowed_source_systems: Optional[Set[str]] = None,
        blocking_engine: Optional[MultiPathBlockingEngine] = None,
    ):
        """
        Initialize the Candidate Generator.

        :param entity_pool: ACCOUNT or CONTACT.
        :param candidate_ceiling: Maximum unique pairs allowed before breach (default 200,000).
        :param max_group_size: Maximum records in a single group before flagging as oversized (default 500).
        :param allowed_source_systems: Override set of permitted source system codes.
        :param blocking_engine: Custom MultiPathBlockingEngine instance or None.
        """
        self.entity_pool = entity_pool.upper()
        if self.entity_pool not in (EntityPool.ACCOUNT.value, EntityPool.CONTACT.value):
            raise ValueError(f"Unsupported entity pool: {entity_pool}")

        self.candidate_ceiling = candidate_ceiling
        self.max_group_size = max_group_size
        self.allowed_source_systems = (
            allowed_source_systems or POOL_SYSTEM_SCOPE.get(self.entity_pool, set())
        )
        self.blocking_engine = blocking_engine or MultiPathBlockingEngine(
            candidate_ceiling=candidate_ceiling,
            max_group_size=max_group_size,
        )

    def filter_and_validate_records(
        self, records: List[SourceRecordInput]
    ) -> Tuple[List[SourceRecordInput], int]:
        """
        Filter out records outside the target pool and allowed source systems.
        Raises ValueError if an explicit cross-pool record is passed.
        Returns: (valid_records, filtered_count)
        """
        valid_records: List[SourceRecordInput] = []
        filtered_count = 0

        for r in records:
            r_pool = r.entity_type.upper()
            if r_pool != self.entity_pool:
                raise ValueError(
                    f"Strict Pool Segregation Violation: Encountered record {r.source_record_id} "
                    f"with entity_type '{r_pool}' in a generator for '{self.entity_pool}'. "
                    f"Cross-pool matching is prohibited."
                )

            # Check source system scope
            sys_code = r.source_system_code.upper()
            if sys_code not in self.allowed_source_systems:
                # Outside scope: reject
                filtered_count += 1
                continue

            valid_records.append(r)

        return valid_records, filtered_count

    def generate_candidate_pairs(
        self,
        records: List[SourceRecordInput],
        matching_run_id: Optional[Union[UUID, str]] = None,
    ) -> CandidateGenerationResult:
        """
        Execute candidate pair generation and deduplication from source records.

        :param records: List of normalized CRM records.
        :param matching_run_id: Optional run ID.
        :return: CandidateGenerationResult with unique candidate pairs and complete stats.
        """
        start_time = time.perf_counter()
        run_id_str = str(matching_run_id) if matching_run_id else None

        stats = CandidateGenerationStats(
            matching_run_id=run_id_str,
            entity_pool=self.entity_pool,
            records_received=len(records),
            ceiling_limit=self.candidate_ceiling,
        )

        # 1. Filter records by run scope
        valid_records, filtered_count = self.filter_and_validate_records(records)
        stats.records_in_scope = len(valid_records)
        stats.records_out_of_scope_filtered = filtered_count

        if not valid_records:
            stats.run_status = "COMPLETED"
            stats.generation_time_seconds = round(time.perf_counter() - start_time, 4)
            return CandidateGenerationResult(
                matching_run_id=run_id_str,
                entity_pool=self.entity_pool,
                candidate_pairs=[],
                stats=stats,
            )

        # 2. Extract blocking paths and build inverted index
        inverted_index: Dict[str, List[Tuple[str, BlockingPath]]] = {}
        for r in valid_records:
            r_id = r.get_id_str()
            paths = self.blocking_engine.extract_blocking_paths(r)
            for path, bucket_key in paths:
                if bucket_key not in inverted_index:
                    inverted_index[bucket_key] = []
                inverted_index[bucket_key].append((r_id, path))

        stats.blocking_groups_evaluated = len(inverted_index)

        # 3. Generate and deduplicate candidate pairs
        deduplicator = PairDeduplicator(entity_pool=self.entity_pool)
        sorted_keys = sorted(inverted_index.keys())

        for bucket_key in sorted_keys:
            bucket = inverted_index[bucket_key]
            bucket_size = len(bucket)

            # Check oversized group protection
            if bucket_size > self.max_group_size:
                expected_pairs = bucket_size * (bucket_size - 1) // 2
                stats.oversized_groups_count += 1
                stats.oversized_groups_details.append(
                    {
                        "bucket_key": bucket_key,
                        "size": bucket_size,
                        "threshold": self.max_group_size,
                        "expected_pairs": expected_pairs,
                        "action": "SKIPPED_TO_PREVENT_COMBINATORIAL_EXPLOSION",
                    }
                )
                continue

            # Pairwise generation
            for i in range(bucket_size):
                id_a, path_a = bucket[i]
                for j in range(i + 1, bucket_size):
                    id_b, path_b = bucket[j]

                    if id_a == id_b:
                        continue  # Self-pair rejected

                    # Canonical order: left < right
                    if id_a < id_b:
                        left_id, right_id = id_a, id_b
                    else:
                        left_id, right_id = id_b, id_a

                    pair_key = (left_id, right_id)

                    # Check ceiling breach BEFORE adding a new unique pair
                    # Rule: 200,000 allowed to complete; 200,001 triggers HELD_CEILING_BREACH
                    is_new_pair = (pair_key not in deduplicator._pairs)
                    if is_new_pair and deduplicator.count() >= self.candidate_ceiling:
                        stats.ceiling_breached = True
                        stats.run_status = "HELD_CEILING_BREACH"
                        break

                    deduplicator.add_pair(
                        id_a=left_id,
                        id_b=right_id,
                        path=path_a,
                        entity_type=self.entity_pool,
                        matching_run_id=run_id_str,
                    )

                if stats.ceiling_breached:
                    break

            if stats.ceiling_breached:
                break

        # 4. Compile statistics
        dedup_stats = deduplicator.get_stats()
        stats.raw_pairs_generated = dedup_stats.raw_pairs_received
        stats.duplicate_pairs_pruned = dedup_stats.duplicate_pairs_merged
        stats.unique_candidates_count = dedup_stats.unique_pairs_count
        stats.multi_path_candidates_count = dedup_stats.multi_path_pairs_count
        stats.deduplication_stats = dedup_stats

        if stats.ceiling_breached:
            stats.run_status = "HELD_CEILING_BREACH"
        else:
            stats.run_status = "COMPLETED"

        stats.generation_time_seconds = round(time.perf_counter() - start_time, 4)
        unique_pairs = deduplicator.get_unique_pairs()

        return CandidateGenerationResult(
            matching_run_id=run_id_str,
            entity_pool=self.entity_pool,
            candidate_pairs=unique_pairs,
            stats=stats,
        )

    def persist_candidates(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        candidate_pairs: List[BlockingCandidatePair],
        batch_size: int = 1000,
        ceiling_breached: bool = False,
    ) -> int:
        """
        Persist candidate pairs and their blocking paths into the database.
        Idempotent: If run already has pairs, skips duplicates cleanly.
        Transaction-safe: Rolls back fully on database errors.

        :param session: SQLAlchemy session.
        :param matching_run_id: The MatchingRun UUID or str.
        :param candidate_pairs: List of deduplicated candidate pairs to persist.
        :param batch_size: Chunk size for bulk insertions.
        :param ceiling_breached: Flag indicating whether candidate ceiling was breached.
        :return: Number of candidate pairs persisted.
        """
        run_uuid = UUID(str(matching_run_id)) if not isinstance(matching_run_id, UUID) else matching_run_id
        start_time = time.perf_counter()

        try:
            # 1. Fetch matching run record
            match_run = session.execute(
                select(MatchingRun).where(MatchingRun.id == run_uuid)
            ).scalar_one_or_none()

            # Query existing candidate pairs for this run to ensure idempotency on rerun
            existing_pairs_query = session.execute(
                select(
                    CandidatePair.id,
                    CandidatePair.left_source_record_id,
                    CandidatePair.right_source_record_id,
                ).where(CandidatePair.matching_run_id == run_uuid)
            ).all()

            # Map (left_uuid_str, right_uuid_str) -> candidate_pair_id
            existing_pair_map: Dict[Tuple[str, str], UUID] = {
                (str(r.left_source_record_id), str(r.right_source_record_id)): r.id
                for r in existing_pairs_query
            }

            # Query existing blocking paths to prevent duplicate key insertion on retry
            existing_paths_set: Set[Tuple[UUID, str, str]] = set()
            if existing_pair_map:
                existing_pair_ids = list(existing_pair_map.values())
                # Chunk if large
                for i in range(0, len(existing_pair_ids), 500):
                    id_chunk = existing_pair_ids[i : i + 500]
                    paths_q = session.execute(
                        select(
                            CandidateBlockingPath.candidate_pair_id,
                            CandidateBlockingPath.blocking_key_name,
                            CandidateBlockingPath.blocking_value,
                        ).where(CandidateBlockingPath.candidate_pair_id.in_(id_chunk))
                    ).all()
                    for p in paths_q:
                        existing_paths_set.add(
                            (p.candidate_pair_id, p.blocking_key_name, p.blocking_value)
                        )

            pairs_to_insert = []
            paths_to_insert = []

            for pair in candidate_pairs:
                left_uuid = UUID(str(pair.left_source_record_id))
                right_uuid = UUID(str(pair.right_source_record_id))
                pair_tuple = (str(left_uuid), str(right_uuid))

                if pair_tuple in existing_pair_map:
                    pair_id = existing_pair_map[pair_tuple]
                else:
                    pair_id = uuid.uuid4()
                    pairs_to_insert.append(
                        {
                            "id": pair_id,
                            "matching_run_id": run_uuid,
                            "left_source_record_id": left_uuid,
                            "right_source_record_id": right_uuid,
                            "entity_type": self.entity_pool,
                            "total_score": 0.0,
                            "decision_tier": "PENDING_SCORING",
                            "proposed_category": "REVIEW",
                            "is_migrated_legacy": False,
                        }
                    )
                    existing_pair_map[pair_tuple] = pair_id

                # Attach blocking paths idempotently
                for bp in pair.blocking_paths:
                    path_key = (pair_id, bp.blocking_key_name, bp.blocking_value)
                    if path_key not in existing_paths_set:
                        paths_to_insert.append(
                            {
                                "id": uuid.uuid4(),
                                "candidate_pair_id": pair_id,
                                "blocking_key_name": bp.blocking_key_name,
                                "blocking_value": bp.blocking_value,
                            }
                        )
                        existing_paths_set.add(path_key)

            # 2. Bulk insert candidate pairs in chunks
            if pairs_to_insert:
                for i in range(0, len(pairs_to_insert), batch_size):
                    chunk = pairs_to_insert[i : i + batch_size]
                    session.bulk_insert_mappings(CandidatePair, chunk)

            # 3. Bulk insert candidate blocking paths in chunks
            if paths_to_insert:
                for i in range(0, len(paths_to_insert), batch_size):
                    chunk = paths_to_insert[i : i + batch_size]
                    session.bulk_insert_mappings(CandidateBlockingPath, chunk)

            # 4. Update matching run status & metrics
            if match_run:
                match_run.total_candidates = len(existing_pair_map)
                match_run.ceiling_breached = ceiling_breached
                if ceiling_breached:
                    # Satisfies DB check constraint while indicating HELD_CEILING_BREACH in notes
                    match_run.status = "FAILED"
                    match_run.notes = (
                        f"HELD_CEILING_BREACH: Candidate count exceeded ceiling "
                        f"({self.candidate_ceiling:,} pairs). Run halted to protect system resources."
                    )
                else:
                    match_run.status = "RUNNING"  # Ready for scoring (P2.3.4)

            session.commit()
            return len(pairs_to_insert)

        except Exception as e:
            session.rollback()
            logger.error(f"Persistence transaction failed for run {matching_run_id}: {e}")
            raise
