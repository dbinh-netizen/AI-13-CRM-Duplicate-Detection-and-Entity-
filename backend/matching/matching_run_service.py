"""Matching Run Service & Persistence Manager for SongNhat CRM.

Sub-milestone: P2.3.5 - Evidence Builder & Database Persistence
Module: backend.matching.matching_run_service

Key Responsibilities:
1. Matching Run Lifecycle Management:
   - Governs states ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED') adhering
     strictly to database constraint `chk_match_run_status`.
   - Represents `HELD_CEILING_BREACH` consistently via `ceiling_breached = TRUE`,
     `status = 'FAILED'`, and auditable notes.
2. Transactional & Idempotent Database Persistence:
   - Atomic multi-table batch persistence into `candidate_pairs`,
     `candidate_blocking_paths`, and `candidate_pair_evidence`.
   - Full rollback on failure ensuring no partial or corrupted state is exposed.
   - Idempotent on retry: checks existing records to prevent unique constraint conflicts.
3. Cryptographic Audit Chain (`audit_events`):
   - Emits structured audit events ('CREATE', 'UPDATE') adhering to `chk_audit_action`.
   - Calculates immutable SHA-256 event hash chains for regulatory compliance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.orm import Session

from backend.matching.blocking_engine import BlockingCandidatePair, EntityPool
from backend.matching.evidence_builder import EvidencePackage, EvidenceItemRecord
from backend.models.governance import AuditEvent
from backend.models.intake import MatchingRun
from backend.models.matching import CandidatePair, CandidateBlockingPath, CandidatePairEvidence

logger = logging.getLogger(__name__)


def generate_event_hash(
    previous_hash: Optional[str],
    event_type: str,
    action: str,
    target_type: str,
    target_id: str,
    timestamp_str: str,
    payload: Dict[str, Any],
) -> str:
    """Generate SHA-256 hash for tamper-evident audit chaining."""
    content = (
        f"{previous_hash or 'GENESIS'}|{event_type}|{action}|"
        f"{target_type}|{target_id}|{timestamp_str}|{json.dumps(payload, sort_keys=True)}"
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PersistenceBatchSummary(BaseModel):
    """Auditable metrics summarizing database persistence execution."""

    matching_run_id: str
    pairs_persisted: int = 0
    blocking_paths_persisted: int = 0
    evidence_items_persisted: int = 0
    audit_events_created: int = 0
    duration_seconds: float = 0.0
    is_retry: bool = False
    transaction_committed: bool = False


class MatchingRunService:
    """Service orchestrating MatchingRun lifecycle, transactions, and auditable persistence."""

    def __init__(self, default_actor: str = "system_matching_pipeline"):
        self.default_actor = default_actor
        self._last_event_hashes: Dict[str, str] = {}
        self._last_audit_ts: Optional[datetime] = None

    # -----------------------------------------------------------------------
    # Lifecycle Management
    # -----------------------------------------------------------------------

    def create_matching_run(
        self,
        session: Session,
        run_code: str,
        entity_pool: str,
        policy_id: Optional[Union[UUID, str]] = None,
        candidate_ceiling: int = 200_000,
        notes: Optional[str] = None,
        actor_username: Optional[str] = None,
    ) -> MatchingRun:
        """Create and register a new matching run in PENDING status."""
        pool = entity_pool.upper()
        if pool not in (EntityPool.ACCOUNT.value, EntityPool.CONTACT.value):
            raise ValueError(f"Invalid entity pool for matching run: {entity_pool}")

        run_id = uuid.uuid4()
        pol_uuid = UUID(str(policy_id)) if policy_id else None
        actor = actor_username or self.default_actor

        run = MatchingRun(
            id=run_id,
            run_code=run_code,
            entity_pool=pool,
            status="PENDING",
            policy_id=pol_uuid,
            total_candidates=0,
            ceiling_breached=False,
            notes=notes or f"Matching run {run_code} initialized.",
        )
        session.add(run)
        session.flush()

        # Audit creation
        self.record_audit_event(
            session=session,
            matching_run_id=run_id,
            event_type="MATCHING_RUN_CREATED",
            action="CREATE",
            details={
                "run_code": run_code,
                "entity_pool": pool,
                "candidate_ceiling": candidate_ceiling,
            },
            actor_username=actor,
        )

        session.commit()
        return run

    def start_matching_run(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        actor_username: Optional[str] = None,
    ) -> MatchingRun:
        """Transition matching run from PENDING to RUNNING status."""
        run_uuid = UUID(str(matching_run_id)) if not isinstance(matching_run_id, UUID) else matching_run_id
        run = session.execute(
            select(MatchingRun).where(MatchingRun.id == run_uuid)
        ).scalar_one_or_none()

        if not run:
            raise ValueError(f"MatchingRun not found: {matching_run_id}")

        if run.status != "PENDING":
            logger.warning(f"Run {matching_run_id} is in status '{run.status}', transitioning to RUNNING.")

        run.status = "RUNNING"
        run.started_at = datetime.now(timezone.utc)
        session.flush()

        self.record_audit_event(
            session=session,
            matching_run_id=run_uuid,
            event_type="MATCHING_RUN_STARTED",
            action="UPDATE",
            details={"status": "RUNNING", "started_at": run.started_at.isoformat()},
            actor_username=actor_username or self.default_actor,
        )

        session.commit()
        return run

    def complete_matching_run(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        total_candidates: int,
        actor_username: Optional[str] = None,
    ) -> MatchingRun:
        """Mark matching run as COMPLETED upon full verification."""
        run_uuid = UUID(str(matching_run_id)) if not isinstance(matching_run_id, UUID) else matching_run_id
        run = session.execute(
            select(MatchingRun).where(MatchingRun.id == run_uuid)
        ).scalar_one_or_none()

        if not run:
            raise ValueError(f"MatchingRun not found: {matching_run_id}")

        run.status = "COMPLETED"
        run.total_candidates = total_candidates
        run.completed_at = datetime.now(timezone.utc)
        run.notes = f"Run completed successfully with {total_candidates:,} unique candidate pairs."
        session.flush()

        self.record_audit_event(
            session=session,
            matching_run_id=run_uuid,
            event_type="MATCHING_RUN_COMPLETED",
            action="UPDATE",
            details={
                "status": "COMPLETED",
                "total_candidates": total_candidates,
                "completed_at": run.completed_at.isoformat(),
            },
            actor_username=actor_username or self.default_actor,
        )

        session.commit()
        return run

    def fail_matching_run(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        reason: str,
        error_details: Optional[Dict[str, Any]] = None,
        actor_username: Optional[str] = None,
    ) -> MatchingRun:
        """Mark matching run as FAILED and record audit diagnostics."""
        run_uuid = UUID(str(matching_run_id)) if not isinstance(matching_run_id, UUID) else matching_run_id
        run = session.execute(
            select(MatchingRun).where(MatchingRun.id == run_uuid)
        ).scalar_one_or_none()

        if not run:
            raise ValueError(f"MatchingRun not found: {matching_run_id}")

        run.status = "FAILED"
        run.completed_at = datetime.now(timezone.utc)
        run.notes = f"FAILED: {reason}"
        session.flush()

        details = error_details or {}
        details["failure_reason"] = reason

        self.record_audit_event(
            session=session,
            matching_run_id=run_uuid,
            event_type="MATCHING_RUN_FAILED",
            action="UPDATE",
            details=details,
            actor_username=actor_username or self.default_actor,
        )

        session.commit()
        return run

    def record_ceiling_breach(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        ceiling_limit: int,
        actual_count: int,
        actor_username: Optional[str] = None,
    ) -> MatchingRun:
        """
        Record that candidate ceiling has been breached.
        Adheres to chk_match_run_status by storing status='FAILED', ceiling_breached=TRUE,
        and explicit HELD_CEILING_BREACH in notes.
        """
        run_uuid = UUID(str(matching_run_id)) if not isinstance(matching_run_id, UUID) else matching_run_id
        run = session.execute(
            select(MatchingRun).where(MatchingRun.id == run_uuid)
        ).scalar_one_or_none()

        if not run:
            raise ValueError(f"MatchingRun not found: {matching_run_id}")

        run.status = "FAILED"
        run.ceiling_breached = True
        run.total_candidates = actual_count
        run.completed_at = datetime.now(timezone.utc)
        run.notes = (
            f"HELD_CEILING_BREACH: Candidate count ({actual_count:,}) exceeded "
            f"ceiling ({ceiling_limit:,} pairs). Run halted to protect system resources."
        )
        session.flush()

        self.record_audit_event(
            session=session,
            matching_run_id=run_uuid,
            event_type="CEILING_BREACH_DETECTED",
            action="UPDATE",
            details={
                "ceiling_breached": True,
                "ceiling_limit": ceiling_limit,
                "candidate_count": actual_count,
                "logical_state": "HELD_CEILING_BREACH",
            },
            actor_username=actor_username or self.default_actor,
        )

        session.commit()
        return run

    # -----------------------------------------------------------------------
    # Cryptographic Audit Event Chaining
    # -----------------------------------------------------------------------

    def record_audit_event(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        event_type: str,
        action: str,
        details: Dict[str, Any],
        actor_username: Optional[str] = None,
    ) -> AuditEvent:
        """Append an auditable event with cryptographic hash chaining."""
        run_id_str = str(matching_run_id)
        now_dt = datetime.now(timezone.utc)
        if self._last_audit_ts is not None and now_dt <= self._last_audit_ts:
            now_dt = self._last_audit_ts + timedelta(microseconds=1000)
        self._last_audit_ts = now_dt
        now_str = now_dt.isoformat()
        actor = actor_username or self.default_actor

        # Fetch previous event hash for matching_runs entity
        last_event = self._last_event_hashes.get(run_id_str)
        if last_event is None:
            last_event = session.execute(
                select(AuditEvent.event_hash)
                .where(
                    AuditEvent.target_entity_type == "matching_runs",
                    AuditEvent.target_entity_id == run_id_str,
                )
                .order_by(desc(AuditEvent.created_at))
                .limit(1)
            ).scalar_one_or_none()

        evt_hash = generate_event_hash(
            previous_hash=last_event,
            event_type=event_type,
            action=action,
            target_type="matching_runs",
            target_id=run_id_str,
            timestamp_str=now_str,
            payload=details,
        )
        self._last_event_hashes[run_id_str] = evt_hash

        audit_rec = AuditEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            actor_id=None,
            actor_username=actor,
            target_entity_type="matching_runs",
            target_entity_id=run_id_str,
            action=action,
            details_payload=details,
            previous_event_hash=last_event,
            event_hash=evt_hash,
            created_at=now_dt,
        )
        session.add(audit_rec)
        session.flush()
        return audit_rec

    # -----------------------------------------------------------------------
    # Atomic & Idempotent Multi-Table Persistence
    # -----------------------------------------------------------------------

    def persist_candidates_and_evidence(
        self,
        session: Session,
        matching_run_id: Union[UUID, str],
        candidates: List[BlockingCandidatePair],
        evidence_packages: List[EvidencePackage],
        batch_size: int = 1000,
        actor_username: Optional[str] = None,
    ) -> PersistenceBatchSummary:
        """
        Atomically and idempotently persist candidate pairs, blocking paths,
        and granular evidence into database tables.
        Rolls back completely if an error occurs.
        """
        run_uuid = UUID(str(matching_run_id)) if not isinstance(matching_run_id, UUID) else matching_run_id
        start_t = time.perf_counter()

        summary = PersistenceBatchSummary(
            matching_run_id=str(run_uuid),
        )

        try:
            # 1. Fetch matching run record
            match_run = session.execute(
                select(MatchingRun).where(MatchingRun.id == run_uuid)
            ).scalar_one_or_none()

            if not match_run:
                raise ValueError(f"Cannot persist: MatchingRun '{matching_run_id}' does not exist.")

            # Record audit: persistence started
            self.record_audit_event(
                session=session,
                matching_run_id=run_uuid,
                event_type="EVIDENCE_PERSISTENCE_STARTED",
                action="UPDATE",
                details={
                    "candidates_count": len(candidates),
                    "evidence_packages_count": len(evidence_packages),
                },
                actor_username=actor_username or self.default_actor,
            )

            # 2. Query existing candidate pairs for idempotency on rerun
            existing_pairs = session.execute(
                select(
                    CandidatePair.id,
                    CandidatePair.left_source_record_id,
                    CandidatePair.right_source_record_id,
                ).where(CandidatePair.matching_run_id == run_uuid)
            ).all()

            pair_id_map: Dict[Tuple[str, str], UUID] = {
                (str(p.left_source_record_id), str(p.right_source_record_id)): p.id
                for p in existing_pairs
            }
            if existing_pairs:
                summary.is_retry = True

            # 3. Query existing blocking paths to prevent unique constraint violation on retry
            existing_paths_set: Set[Tuple[UUID, str, str]] = set()
            if pair_id_map:
                pair_ids = list(pair_id_map.values())
                for i in range(0, len(pair_ids), 500):
                    chunk_ids = pair_ids[i : i + 500]
                    paths_q = session.execute(
                        select(
                            CandidateBlockingPath.candidate_pair_id,
                            CandidateBlockingPath.blocking_key_name,
                            CandidateBlockingPath.blocking_value,
                        ).where(CandidateBlockingPath.candidate_pair_id.in_(chunk_ids))
                    ).all()
                    for pt in paths_q:
                        existing_paths_set.add((pt.candidate_pair_id, pt.blocking_key_name, pt.blocking_value))

            # 4. Query existing evidence to prevent duplicate evidence insertion on retry
            existing_evidence_set: Set[Tuple[UUID, str, str]] = set()
            if pair_id_map:
                pair_ids = list(pair_id_map.values())
                for i in range(0, len(pair_ids), 500):
                    chunk_ids = pair_ids[i : i + 500]
                    ev_q = session.execute(
                        select(
                            CandidatePairEvidence.candidate_pair_id,
                            CandidatePairEvidence.rule_name,
                            CandidatePairEvidence.field_name,
                        ).where(CandidatePairEvidence.candidate_pair_id.in_(chunk_ids))
                    ).all()
                    for eq in ev_q:
                        existing_evidence_set.add((eq.candidate_pair_id, eq.rule_name, eq.field_name))

            # 5. Prepare CandidatePair mappings
            # Map candidate tuple to score from evidence packages if available
            score_by_pair: Dict[Tuple[str, str], float] = {
                (pkg.left_source_record_id, pkg.right_source_record_id): pkg.total_score
                for pkg in evidence_packages
            }

            pairs_to_insert = []
            paths_to_insert = []

            for cand in candidates:
                left_uuid = UUID(str(cand.left_source_record_id))
                right_uuid = UUID(str(cand.right_source_record_id))
                tuple_key = (str(left_uuid), str(right_uuid))

                if tuple_key in pair_id_map:
                    cand_id = pair_id_map[tuple_key]
                else:
                    cand_id = uuid.uuid4()
                    pair_id_map[tuple_key] = cand_id

                    total_score = score_by_pair.get(tuple_key, 0.0)
                    tier = "HIGH_CONFIDENCE" if total_score >= 85.0 else ("SUSPECTED" if total_score >= 60.0 else "LOW_CONFIDENCE")
                    cat = "MERGE_CANDIDATE" if total_score >= 85.0 else "REVIEW"

                    pairs_to_insert.append(
                        {
                            "id": cand_id,
                            "matching_run_id": run_uuid,
                            "left_source_record_id": left_uuid,
                            "right_source_record_id": right_uuid,
                            "entity_type": match_run.entity_pool,
                            "total_score": total_score,
                            "decision_tier": tier,
                            "proposed_category": cat,
                            "is_migrated_legacy": False,
                        }
                    )

                # Attach blocking paths idempotently
                for bp in cand.blocking_paths:
                    bp_key = (cand_id, bp.blocking_key_name, bp.blocking_value)
                    if bp_key not in existing_paths_set:
                        paths_to_insert.append(
                            {
                                "id": uuid.uuid4(),
                                "candidate_pair_id": cand_id,
                                "blocking_key_name": bp.blocking_key_name,
                                "blocking_value": bp.blocking_value,
                            }
                        )
                        existing_paths_set.add(bp_key)

            # 6. Bulk Insert Candidate Pairs
            if pairs_to_insert:
                for i in range(0, len(pairs_to_insert), batch_size):
                    chunk = pairs_to_insert[i : i + batch_size]
                    session.bulk_insert_mappings(CandidatePair, chunk)
                summary.pairs_persisted = len(pairs_to_insert)

            # 7. Bulk Insert Candidate Blocking Paths
            if paths_to_insert:
                for i in range(0, len(paths_to_insert), batch_size):
                    chunk = paths_to_insert[i : i + batch_size]
                    session.bulk_insert_mappings(CandidateBlockingPath, chunk)
                summary.blocking_paths_persisted = len(paths_to_insert)

            # 8. Prepare and Bulk Insert Candidate Pair Evidence
            evidence_to_insert = []
            for pkg in evidence_packages:
                tuple_key = (pkg.left_source_record_id, pkg.right_source_record_id)
                cand_id = pair_id_map.get(tuple_key)
                if not cand_id:
                    # Look up using UUID string
                    cand_id = pair_id_map.get((str(UUID(pkg.left_source_record_id)), str(UUID(pkg.right_source_record_id))))

                if not cand_id:
                    logger.warning(f"Skipping evidence package for unpersisted pair: {tuple_key}")
                    continue

                for item in pkg.evidence_items:
                    ev_key = (cand_id, item.rule_name, item.field_name)
                    if ev_key not in existing_evidence_set:
                        evidence_to_insert.append(
                            {
                                "id": uuid.uuid4(),
                                "candidate_pair_id": cand_id,
                                "rule_name": item.rule_name,
                                "field_name": item.field_name,
                                "left_raw_value": item.left_raw_value,
                                "right_raw_value": item.right_raw_value,
                                "left_normalized_value": item.left_normalized_value,
                                "right_normalized_value": item.right_normalized_value,
                                "similarity_score": item.similarity_score,
                                "evidence_direction": item.evidence_direction,
                                "evidence_weight": item.evidence_weight,
                                "is_legacy_evidence": False,
                                "provenance": (item.provenance or "PIPELINE_CALCULATED")[:100],
                                "policy_version": item.policy_version,
                            }
                        )
                        existing_evidence_set.add(ev_key)

            if evidence_to_insert:
                for i in range(0, len(evidence_to_insert), batch_size):
                    chunk = evidence_to_insert[i : i + batch_size]
                    session.bulk_insert_mappings(CandidatePairEvidence, chunk)
                summary.evidence_items_persisted = len(evidence_to_insert)

            # Update matching run count
            match_run.total_candidates = len(pair_id_map)

            # Record audit: persistence completed
            self.record_audit_event(
                session=session,
                matching_run_id=run_uuid,
                event_type="EVIDENCE_PERSISTENCE_COMPLETED",
                action="UPDATE",
                details={
                    "pairs_persisted": summary.pairs_persisted,
                    "blocking_paths_persisted": summary.blocking_paths_persisted,
                    "evidence_items_persisted": summary.evidence_items_persisted,
                    "total_unique_pairs": match_run.total_candidates,
                },
                actor_username=actor_username or self.default_actor,
            )

            # Atomic commit of transaction
            session.commit()
            summary.transaction_committed = True
            summary.duration_seconds = round(time.perf_counter() - start_t, 4)
            return summary

        except Exception as e:
            session.rollback()
            summary.transaction_committed = False
            summary.duration_seconds = round(time.perf_counter() - start_t, 4)
            logger.error(f"Persistence transaction failed for run {matching_run_id}: {e}")
            raise
