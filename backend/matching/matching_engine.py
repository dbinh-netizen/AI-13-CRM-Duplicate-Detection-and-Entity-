"""Unified Matching Engine Orchestrator for SongNhat CRM Duplicate Detection & Entity Resolution.

Sub-milestone: P2.3.6 - Full & Incremental Matching Orchestration
Module: backend.matching.matching_engine

Orchestrates the entire end-to-end matching pipeline across all 6 core modules:
1. Input Contract Validation & Run Scope Enforcement
2. Lifecycle Governance via MatchingRunService
3. Multi-path Blocking via MultiPathBlockingEngine
4. Candidate Generation & Deduplication via PairDeduplicator
5. Strict Candidate Ceiling Enforcement (200,000 max pairs)
6. Fine-grained Similarity Scoring via SimilarityScorer
7. Auditable Evidence Generation via EvidenceBuilder
8. Transactional & Idempotent Database Persistence
9. Mathematical Reconciliation & Observability Audit Events

Supports:
- FULL Matching Runs (complete pool comparison: CRM_A, CRM_B within and cross-source; CRM_C within-source)
- INCREMENTAL Matching Runs (delta-to-delta, delta-to-existing cross comparison without redundant existing-existing enumeration)
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.matching.blocking_engine import (
    BlockingCandidatePair,
    BlockingPath,
    BlockingStrategy,
    EntityPool,
    MultiPathBlockingEngine,
    SourceRecordInput,
)
from backend.matching.candidate_generator import POOL_SYSTEM_SCOPE
from backend.matching.evidence_builder import (
    EvidenceBuilder,
    EvidenceItemRecord,
    EvidencePackage,
)
from backend.matching.matching_run_service import (
    MatchingRunService,
    PersistenceBatchSummary,
)
from backend.matching.pair_deduplicator import PairDeduplicator
from backend.matching.similarity_scorer import (
    DEFAULT_ACCOUNT_SCORING_POLICY,
    DEFAULT_CONTACT_SCORING_POLICY,
    PairScoringResult,
    ScoringPolicy,
    SimilarityScorer,
)
from backend.models.intake import MatchingRun

logger = logging.getLogger(__name__)


class MatchingRunType(str, Enum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"


class MatchingRunRequest(BaseModel):
    """Execution request contract for starting a matching pipeline run."""

    run_code: Optional[str] = None
    entity_pool: str = "ACCOUNT"  # "ACCOUNT" or "CONTACT"
    run_type: MatchingRunType = MatchingRunType.FULL
    source_system_codes: Optional[List[str]] = None
    import_batch_ids: Optional[List[Union[UUID, str]]] = None
    policy_id: Optional[Union[UUID, str]] = None
    candidate_ceiling: int = 200_000
    max_group_size: int = 500
    actor_username: str = "system_matching_pipeline"
    normalization_policy_version: str = "1.0"
    scoring_policy_version: str = "1.0-EXPERIMENTAL"
    scoring_policy: Optional[ScoringPolicy] = None


class ReconciliationReport(BaseModel):
    """End-of-run reconciliation audit between input, intermediate, and persisted entities."""

    records_scanned: int = 0
    records_accepted: int = 0
    records_filtered_out_of_scope: int = 0
    delta_records_count: int = 0
    existing_records_count: int = 0
    blocking_groups_count: int = 0
    raw_candidate_pairs_generated: int = 0
    duplicate_pairs_pruned: int = 0
    unique_candidate_pairs: int = 0
    scored_candidate_pairs: int = 0
    evidence_packages_built: int = 0
    total_evidence_items: int = 0
    persisted_candidate_pairs: int = 0
    persisted_evidence_rows: int = 0
    persisted_blocking_paths: int = 0
    reconciliation_passed: bool = True
    discrepancy_notes: List[str] = Field(default_factory=list)


class MatchingPipelineResult(BaseModel):
    """Comprehensive output package returned by the MatchingEngine."""

    matching_run_id: str
    run_code: str
    entity_pool: str
    run_type: str
    status: str  # "COMPLETED", "HELD_CEILING_BREACH", "FAILED"
    ceiling_breached: bool = False
    total_candidates: int = 0
    candidate_pairs: List[BlockingCandidatePair] = Field(default_factory=list)
    scoring_results: List[PairScoringResult] = Field(default_factory=list)
    evidence_packages: List[EvidencePackage] = Field(default_factory=list)
    reconciliation: ReconciliationReport = Field(default_factory=ReconciliationReport)
    stage_durations: Dict[str, float] = Field(default_factory=dict)
    total_duration_seconds: float = 0.0
    error_stage: Optional[str] = None
    error_message: Optional[str] = None


class MatchingEngine:
    """Unified Orchestrator coordinating Full and Incremental matching runs."""

    def __init__(
        self,
        service: Optional[MatchingRunService] = None,
        blocking_engine: Optional[MultiPathBlockingEngine] = None,
    ):
        self.service = service or MatchingRunService()
        self.blocking_engine = blocking_engine or MultiPathBlockingEngine()

    def validate_request(self, request: MatchingRunRequest) -> None:
        """Validate input parameters against architectural contracts."""
        pool = request.entity_pool.upper()
        if pool not in (EntityPool.ACCOUNT.value, EntityPool.CONTACT.value):
            raise ValueError(f"Invalid entity pool '{request.entity_pool}'. Must be ACCOUNT or CONTACT.")

        if request.candidate_ceiling <= 0:
            raise ValueError(f"Candidate ceiling must be positive, got {request.candidate_ceiling}.")

        allowed_systems = POOL_SYSTEM_SCOPE.get(pool, set())
        if request.source_system_codes:
            for sys_code in request.source_system_codes:
                if sys_code.upper() not in allowed_systems:
                    raise ValueError(
                        f"Scope violation: System '{sys_code}' is not permitted in pool '{pool}'. "
                        f"Allowed systems: {sorted(allowed_systems)}."
                    )

        # Check for duplicate batch IDs
        if request.import_batch_ids:
            batch_strs = [str(b) for b in request.import_batch_ids]
            if len(batch_strs) != len(set(batch_strs)):
                raise ValueError("Duplicate import_batch_ids found in request.")

    def execute_matching_run(
        self,
        request: MatchingRunRequest,
        records: Optional[List[SourceRecordInput]] = None,
        delta_records: Optional[List[SourceRecordInput]] = None,
        existing_records: Optional[List[SourceRecordInput]] = None,
        session: Optional[Session] = None,
    ) -> MatchingPipelineResult:
        """
        Execute an end-to-end matching pipeline (FULL or INCREMENTAL).

        :param request: Matching run parameters.
        :param records: Full dataset for FULL run.
        :param delta_records: Delta changed/new records for INCREMENTAL run.
        :param existing_records: Existing unchanged pool records for INCREMENTAL run.
        :param session: Optional SQLAlchemy session for database persistence.
        :return: MatchingPipelineResult with full diagnostic and auditable metadata.
        """
        pipeline_start_t = time.perf_counter()
        stage_times: Dict[str, float] = {}
        reconciliation = ReconciliationReport()

        # Step 1: Validate request
        t0 = time.perf_counter()
        self.validate_request(request)
        stage_times["request_validation"] = round(time.perf_counter() - t0, 4)

        pool = request.entity_pool.upper()
        allowed_systems = (
            set(c.upper() for c in request.source_system_codes)
            if request.source_system_codes
            else POOL_SYSTEM_SCOPE.get(pool, set())
        )

        run_code = request.run_code or f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{pool}-{request.run_type.value}"
        run_uuid = uuid.uuid4()
        run_id_str = str(run_uuid)

        # Step 2: Register & Start Run in Database if session provided
        t0 = time.perf_counter()
        if session:
            db_run = self.service.create_matching_run(
                session=session,
                run_code=run_code,
                entity_pool=pool,
                policy_id=request.policy_id,
                candidate_ceiling=request.candidate_ceiling,
                actor_username=request.actor_username,
            )
            run_uuid = db_run.id
            run_id_str = str(run_uuid)
            self.service.start_matching_run(
                session=session,
                matching_run_id=run_uuid,
                actor_username=request.actor_username,
            )
        stage_times["run_initialization"] = round(time.perf_counter() - t0, 4)

        try:
            # Step 3: Scope Resolution & Record Segregation
            t0 = time.perf_counter()
            all_records_map: Dict[str, SourceRecordInput] = {}
            delta_ids: Set[str] = set()

            if request.run_type == MatchingRunType.FULL:
                input_records = records or []
                reconciliation.records_scanned = len(input_records)

                for r in input_records:
                    if r.entity_type.upper() != pool:
                        raise ValueError(
                            f"Strict Pool Segregation Violation: Encountered {r.entity_type} "
                            f"record {r.source_record_id} in {pool} FULL run."
                        )
                    if r.source_system_code.upper() not in allowed_systems:
                        reconciliation.records_filtered_out_of_scope += 1
                        continue

                    all_records_map[r.get_id_str()] = r
                    reconciliation.records_accepted += 1

                # In FULL run, all accepted records can match with each other
                delta_ids = set(all_records_map.keys())

            else:
                # INCREMENTAL run
                d_recs = delta_records or []
                e_recs = existing_records or []

                reconciliation.delta_records_count = len(d_recs)
                reconciliation.existing_records_count = len(e_recs)
                reconciliation.records_scanned = len(d_recs) + len(e_recs)

                # Process delta records
                for r in d_recs:
                    if r.entity_type.upper() != pool:
                        raise ValueError(
                            f"Strict Pool Segregation Violation: Encountered {r.entity_type} "
                            f"record {r.source_record_id} in {pool} delta batch."
                        )
                    if r.source_system_code.upper() not in allowed_systems:
                        reconciliation.records_filtered_out_of_scope += 1
                        continue

                    r_id = r.get_id_str()
                    all_records_map[r_id] = r
                    delta_ids.add(r_id)
                    reconciliation.records_accepted += 1

                # Process existing unchanged records (for cross-comparison with delta)
                for r in e_recs:
                    if r.entity_type.upper() != pool:
                        raise ValueError(
                            f"Strict Pool Segregation Violation: Encountered {r.entity_type} "
                            f"record {r.source_record_id} in existing records pool."
                        )
                    if r.source_system_code.upper() not in allowed_systems:
                        continue

                    r_id = r.get_id_str()
                    # Do not overwrite if delta record already loaded
                    if r_id not in all_records_map:
                        all_records_map[r_id] = r

            stage_times["scope_resolution"] = round(time.perf_counter() - t0, 4)

            # Step 4: Multi-Path Blocking Index Construction
            t0 = time.perf_counter()
            inverted_index: Dict[str, List[Tuple[str, BlockingPath]]] = {}
            for r_id, record in all_records_map.items():
                paths = self.blocking_engine.extract_blocking_paths(record)
                for path, bucket_key in paths:
                    if bucket_key not in inverted_index:
                        inverted_index[bucket_key] = []
                    inverted_index[bucket_key].append((r_id, path))

            reconciliation.blocking_groups_count = len(inverted_index)
            stage_times["blocking"] = round(time.perf_counter() - t0, 4)

            # Step 5: Candidate Pair Generation & Multi-Path Deduplication
            t0 = time.perf_counter()
            deduplicator = PairDeduplicator(entity_pool=pool)
            ceiling_breached = False

            sorted_bucket_keys = sorted(inverted_index.keys())
            for bucket_key in sorted_bucket_keys:
                bucket = inverted_index[bucket_key]
                bucket_size = len(bucket)

                # Oversized group protection
                if bucket_size > request.max_group_size:
                    continue

                for i in range(bucket_size):
                    id_a, path_a = bucket[i]
                    for j in range(i + 1, bucket_size):
                        id_b, path_b = bucket[j]

                        # Skip self-pairs
                        if id_a == id_b:
                            continue

                        # INCREMENTAL RULE: At least ONE record must belong to delta_ids!
                        # (We skip pairs where both id_a and id_b are existing unchanged records)
                        if request.run_type == MatchingRunType.INCREMENTAL:
                            if id_a not in delta_ids and id_b not in delta_ids:
                                continue

                        reconciliation.raw_candidate_pairs_generated += 1

                        # Canonical ordering: left < right
                        left_id, right_id = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                        pair_key = (left_id, right_id)

                        # Ceiling check: 200,000 allowed, 200,001 breached
                        is_new = (pair_key not in deduplicator._pairs)
                        if is_new and deduplicator.count() >= request.candidate_ceiling:
                            ceiling_breached = True
                            break

                        deduplicator.add_pair(
                            id_a=left_id,
                            id_b=right_id,
                            path=path_a,
                            entity_type=pool,
                            matching_run_id=run_id_str,
                        )

                    if ceiling_breached:
                        break
                if ceiling_breached:
                    break

            unique_candidates = deduplicator.get_unique_pairs()
            dedup_stats = deduplicator.get_stats()
            reconciliation.duplicate_pairs_pruned = dedup_stats.duplicate_pairs_merged
            reconciliation.unique_candidate_pairs = len(unique_candidates)
            stage_times["candidate_generation"] = round(time.perf_counter() - t0, 4)

            # Handle Ceiling Breach
            if ceiling_breached:
                reconciliation.discrepancy_notes.append(
                    f"Candidate ceiling breached: limit is {request.candidate_ceiling:,} pairs."
                )
                if session:
                    self.service.record_ceiling_breach(
                        session=session,
                        matching_run_id=run_uuid,
                        ceiling_limit=request.candidate_ceiling,
                        actual_count=len(unique_candidates) + 1,
                        actor_username=request.actor_username,
                    )

                total_time = round(time.perf_counter() - pipeline_start_t, 4)
                return MatchingPipelineResult(
                    matching_run_id=run_id_str,
                    run_code=run_code,
                    entity_pool=pool,
                    run_type=request.run_type.value,
                    status="HELD_CEILING_BREACH",
                    ceiling_breached=True,
                    total_candidates=len(unique_candidates),
                    candidate_pairs=unique_candidates,
                    reconciliation=reconciliation,
                    stage_durations=stage_times,
                    total_duration_seconds=total_time,
                )

            # Step 6: Similarity Scoring
            t0 = time.perf_counter()
            policy = request.scoring_policy
            if policy is None and request.scoring_policy_version:
                base_policy = (
                    DEFAULT_ACCOUNT_SCORING_POLICY
                    if pool == EntityPool.ACCOUNT.value
                    else DEFAULT_CONTACT_SCORING_POLICY
                )
                policy = base_policy.model_copy(update={"version": request.scoring_policy_version})

            scorer = SimilarityScorer(
                entity_pool=pool,
                scoring_policy=policy,
                normalization_policy_version=request.normalization_policy_version,
            )
            scoring_results: List[PairScoringResult] = []

            for cand in unique_candidates:
                left_rec = all_records_map[cand.left_source_record_id]
                right_rec = all_records_map[cand.right_source_record_id]
                s_res = scorer.score_candidate_pair(
                    left=left_rec,
                    right=right_rec,
                    matching_run_id=run_id_str,
                )
                scoring_results.append(s_res)

            reconciliation.scored_candidate_pairs = len(scoring_results)
            stage_times["similarity_scoring"] = round(time.perf_counter() - t0, 4)

            # Step 7: Auditable Evidence Building
            t0 = time.perf_counter()
            builder = EvidenceBuilder(
                entity_pool=pool,
                normalization_policy_version=request.normalization_policy_version,
                scoring_policy_version=request.scoring_policy_version,
            )
            evidence_packages: List[EvidencePackage] = []

            for cand, s_res in zip(unique_candidates, scoring_results):
                left_rec = all_records_map[cand.left_source_record_id]
                right_rec = all_records_map[cand.right_source_record_id]
                pkg = builder.build_evidence(
                    candidate_pair_id=str(uuid.uuid4()),
                    left=left_rec,
                    right=right_rec,
                    scoring_result=s_res,
                    matching_run_id=run_id_str,
                )
                evidence_packages.append(pkg)
                reconciliation.total_evidence_items += len(pkg.evidence_items)

            reconciliation.evidence_packages_built = len(evidence_packages)
            stage_times["evidence_building"] = round(time.perf_counter() - t0, 4)

            # Step 8: Database Persistence (Atomic Multi-Table Batch Insert)
            t0 = time.perf_counter()
            if session:
                summary = self.service.persist_candidates_and_evidence(
                    session=session,
                    matching_run_id=run_uuid,
                    candidates=unique_candidates,
                    evidence_packages=evidence_packages,
                    batch_size=2000,
                    actor_username=request.actor_username,
                )
                reconciliation.persisted_candidate_pairs = summary.pairs_persisted
                reconciliation.persisted_evidence_rows = summary.evidence_items_persisted
                reconciliation.persisted_blocking_paths = summary.blocking_paths_persisted
            else:
                reconciliation.persisted_candidate_pairs = len(unique_candidates)
                reconciliation.persisted_evidence_rows = reconciliation.total_evidence_items
                reconciliation.persisted_blocking_paths = sum(len(c.blocking_paths) for c in unique_candidates)
            stage_times["database_persistence"] = round(time.perf_counter() - t0, 4)

            # Step 9: Reconciliation Audit & Run Completion
            t0 = time.perf_counter()
            # Verify counts match
            if reconciliation.unique_candidate_pairs != reconciliation.scored_candidate_pairs:
                reconciliation.reconciliation_passed = False
                reconciliation.discrepancy_notes.append("Mismatch between unique candidates and scored candidates.")

            if reconciliation.unique_candidate_pairs != reconciliation.evidence_packages_built:
                reconciliation.reconciliation_passed = False
                reconciliation.discrepancy_notes.append("Mismatch between unique candidates and evidence packages.")

            if not reconciliation.reconciliation_passed:
                if session:
                    self.service.fail_matching_run(
                        session=session,
                        matching_run_id=run_uuid,
                        reason="; ".join(reconciliation.discrepancy_notes),
                        actor_username=request.actor_username,
                    )
                status_str = "FAILED"
            else:
                if session:
                    self.service.complete_matching_run(
                        session=session,
                        matching_run_id=run_uuid,
                        total_candidates=len(unique_candidates),
                        actor_username=request.actor_username,
                    )
                status_str = "COMPLETED"

            stage_times["reconciliation_finalization"] = round(time.perf_counter() - t0, 4)
            total_duration = round(time.perf_counter() - pipeline_start_t, 4)

            return MatchingPipelineResult(
                matching_run_id=run_id_str,
                run_code=run_code,
                entity_pool=pool,
                run_type=request.run_type.value,
                status=status_str,
                ceiling_breached=False,
                total_candidates=len(unique_candidates),
                candidate_pairs=unique_candidates,
                scoring_results=scoring_results,
                evidence_packages=evidence_packages,
                reconciliation=reconciliation,
                stage_durations=stage_times,
                total_duration_seconds=total_duration,
            )

        except Exception as e:
            total_duration = round(time.perf_counter() - pipeline_start_t, 4)
            logger.error(f"Matching pipeline failed during execution: {e}")
            if session:
                try:
                    self.service.fail_matching_run(
                        session=session,
                        matching_run_id=run_uuid,
                        reason=str(e),
                        actor_username=request.actor_username,
                    )
                except Exception:
                    pass

            raise
