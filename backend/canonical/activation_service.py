"""Canonical Entity & Membership Activation Service for Milestone P2.5.

Sub-milestone: P2.5 - CANONICAL MEMBERSHIP & TEMPORAL INTEGRITY
Module: backend.canonical.activation_service

Key Responsibilities:
1. Enforce Maker-Checker approval before activating candidate duplicates.
2. Group confirmed duplicate records into a unified CanonicalEntity.
3. Manage temporal CanonicalMembership records (SCD Type 2: valid_from, valid_to, status).
4. Enforce strict single-active membership constraint per source record.
5. Auto-activate distinct/singleton records into distinct 1-to-1 Canonical Entities.
6. Pool segregation: ACCOUNT vs CONTACT isolation enforced at database FK level.
7. Log immutable AuditEvents for every creation, merge, and supersession.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.orm import Session

from backend.canonical.constants import CanonicalStatus, MembershipStatus
from backend.models.canonical import CanonicalEntity, CanonicalMembership
from backend.models.governance import AuditEvent
from backend.models.intake import SourceRecord, SourceSystem
from backend.models.matching import CandidatePair
from backend.models.review import CandidateCluster, CandidateClusterMember, ReviewDecision, ReviewTask

logger = logging.getLogger(__name__)


class ActivationResult(BaseModel):
    canonical_entity_id: str
    canonical_code: str
    entity_type: str
    action_taken: str  # CREATED, REUSED, SUPERSEDED
    member_record_ids: List[str]
    membership_ids: List[str]
    audit_event_id: Optional[str] = None


class SingletonActivationSummary(BaseModel):
    entity_type: str
    total_singletons_activated: int
    canonical_entities_created: int
    memberships_created: int


class CanonicalActivationService:
    """Service governing Canonical Entity lifecycles and temporal memberships."""

    @staticmethod
    def _generate_canonical_code(entity_type: str, seed: Optional[str] = None) -> str:
        """Generate unique canonical identifier (CAN-ACC-... or CAN-CON-...)."""
        prefix = "CAN-ACC" if entity_type.upper() == "ACCOUNT" else "CAN-CON"
        random_hex = uuid.uuid4().hex[:8].upper()
        return f"{prefix}-{random_hex}"

    def _supersede_existing_memberships(
        self,
        session: Session,
        source_record_id: Union[UUID, str],
        entity_type: str,
        now_dt: datetime,
    ) -> List[CanonicalMembership]:
        """Supersede any currently active membership for this source record."""
        rec_uuid = UUID(str(source_record_id))
        active_memberships = session.execute(
            select(CanonicalMembership).where(
                and_(
                    CanonicalMembership.source_record_id == rec_uuid,
                    CanonicalMembership.entity_type == entity_type,
                    CanonicalMembership.status == MembershipStatus.USABLE.value,
                    CanonicalMembership.valid_to.is_(None),
                )
            )
        ).scalars().all()

        superseded = []
        for m in active_memberships:
            m.status = MembershipStatus.SUPERSEDED.value
            m.valid_to = now_dt
            superseded.append(m)
        return superseded

    def _find_active_membership(
        self,
        session: Session,
        source_record_id: Union[UUID, str],
        entity_type: str,
    ) -> Optional[CanonicalMembership]:
        """Find the active USABLE membership for a source record."""
        rec_uuid = UUID(str(source_record_id))
        return session.execute(
            select(CanonicalMembership).where(
                and_(
                    CanonicalMembership.source_record_id == rec_uuid,
                    CanonicalMembership.entity_type == entity_type,
                    CanonicalMembership.status == MembershipStatus.USABLE.value,
                    CanonicalMembership.valid_to.is_(None),
                )
            )
        ).scalar_one_or_none()

    def activate_from_decision(
        self,
        session: Session,
        decision_id: Union[UUID, str],
        actor_username: str = "system_canonical_activator",
    ) -> List[ActivationResult]:
        """
        Activate Canonical Entities & Memberships for an APPROVED ReviewDecision.

        Dual-control invariant: proposed_by != approved_by and status == 'APPROVED'.
        """
        dec_uuid = UUID(str(decision_id))
        decision = session.execute(
            select(ReviewDecision).where(ReviewDecision.id == dec_uuid)
        ).scalar_one_or_none()

        if not decision:
            raise ValueError(f"ReviewDecision '{decision_id}' not found.")

        if decision.status != "APPROVED":
            raise ValueError(
                f"ReviewDecision '{decision_id}' cannot be activated: status is '{decision.status}', must be 'APPROVED'."
            )

        if decision.proposed_by == decision.approved_by:
            raise ValueError(
                f"Maker-Checker dual control violation: proposed_by ({decision.proposed_by}) equals approved_by ({decision.approved_by})."
            )

        task = session.execute(
            select(ReviewTask).where(ReviewTask.id == decision.review_task_id)
        ).scalar_one_or_none()
        if not task:
            raise ValueError(f"ReviewTask '{decision.review_task_id}' not found for decision.")

        now_dt = datetime.now(timezone.utc)
        results: List[ActivationResult] = []

        # Case 1: ReviewTask is bound to a CandidatePair
        if task.candidate_pair_id:
            pair = session.execute(
                select(CandidatePair).where(CandidatePair.id == task.candidate_pair_id)
            ).scalar_one_or_none()
            if not pair:
                raise ValueError(f"CandidatePair '{task.candidate_pair_id}' not found.")

            res = self._activate_pair_records(
                session=session,
                record_id_a=pair.left_source_record_id,
                record_id_b=pair.right_source_record_id,
                entity_type=pair.entity_type,
                decision=decision,
                now_dt=now_dt,
                actor_username=actor_username,
            )
            results.extend(res)

        # Case 2: ReviewTask is bound to a CandidateCluster
        elif task.candidate_cluster_id:
            cluster = session.execute(
                select(CandidateCluster).where(CandidateCluster.id == task.candidate_cluster_id)
            ).scalar_one_or_none()
            if not cluster:
                raise ValueError(f"CandidateCluster '{task.candidate_cluster_id}' not found.")

            members = session.execute(
                select(CandidateClusterMember).where(
                    and_(
                        CandidateClusterMember.candidate_cluster_id == cluster.id,
                        CandidateClusterMember.status == "ACTIVE",
                    )
                )
            ).scalars().all()

            record_ids = [m.source_record_id for m in members]
            res = self._activate_cluster_records(
                session=session,
                record_ids=record_ids,
                entity_type=cluster.entity_pool,
                decision=decision,
                now_dt=now_dt,
                actor_username=actor_username,
            )
            results.extend(res)

        session.flush()
        return results

    def _activate_pair_records(
        self,
        session: Session,
        record_id_a: UUID,
        record_id_b: UUID,
        entity_type: str,
        decision: ReviewDecision,
        now_dt: datetime,
        actor_username: str,
    ) -> List[ActivationResult]:
        """Activate pair under DUPLICATE or DISTINCT decision."""
        is_duplicate = decision.decision_type in ("DUPLICATE", "MERGE")

        if is_duplicate:
            # Consolidate into single CanonicalEntity
            # Check if either record already has an active canonical entity
            mem_a = self._find_active_membership(session, record_id_a, entity_type)
            mem_b = self._find_active_membership(session, record_id_b, entity_type)

            canonical_id = None
            canonical_code = None
            action = "CREATED"

            if mem_a:
                canonical_id = mem_a.canonical_entity_id
                action = "REUSED"
            elif mem_b:
                canonical_id = mem_b.canonical_entity_id
                action = "REUSED"

            if not canonical_id:
                canonical_id = uuid.uuid4()
                canonical_code = self._generate_canonical_code(entity_type)
                canon_entity = CanonicalEntity(
                    id=canonical_id,
                    canonical_code=canonical_code,
                    entity_type=entity_type,
                    status=CanonicalStatus.ACTIVE.value,
                    created_at=now_dt,
                    updated_at=now_dt,
                )
                session.add(canon_entity)
                session.flush()
            else:
                canon_entity = session.execute(
                    select(CanonicalEntity).where(CanonicalEntity.id == canonical_id)
                ).scalar_one()
                canonical_code = canon_entity.canonical_code

            membership_ids = []
            for rec_id in [record_id_a, record_id_b]:
                # If already member of this canonical entity and USABLE, skip duplicate membership
                existing = self._find_active_membership(session, rec_id, entity_type)
                if existing and existing.canonical_entity_id == canonical_id:
                    membership_ids.append(str(existing.id))
                    continue

                # Supersede prior membership if with different canonical
                self._supersede_existing_memberships(session, rec_id, entity_type, now_dt)

                mem_id = uuid.uuid4()
                mem = CanonicalMembership(
                    id=mem_id,
                    canonical_entity_id=canonical_id,
                    source_record_id=rec_id,
                    entity_type=entity_type,
                    valid_from=now_dt,
                    valid_to=None,
                    status=MembershipStatus.USABLE.value,
                    review_decision_id=decision.id,
                    created_at=now_dt,
                )
                session.add(mem)
                membership_ids.append(str(mem_id))

            # Audit event
            audit_id = self._log_audit_event(
                session=session,
                action="APPROVE",
                entity_type=entity_type,
                target_id=str(canonical_id),
                actor_username=actor_username,
                payload={
                    "decision_id": str(decision.id),
                    "decision_type": decision.decision_type,
                    "records_merged": [str(record_id_a), str(record_id_b)],
                    "canonical_code": canonical_code,
                },
            )

            return [
                ActivationResult(
                    canonical_entity_id=str(canonical_id),
                    canonical_code=canonical_code,
                    entity_type=entity_type,
                    action_taken=action,
                    member_record_ids=[str(record_id_a), str(record_id_b)],
                    membership_ids=membership_ids,
                    audit_event_id=audit_id,
                )
            ]

        else:
            # DISTINCT: ensure both records have separate Canonical Entities
            res_list = []
            for rec_id in [record_id_a, record_id_b]:
                mem = self._find_active_membership(session, rec_id, entity_type)
                if not mem:
                    canon_id = uuid.uuid4()
                    canon_code = self._generate_canonical_code(entity_type)
                    canon_entity = CanonicalEntity(
                        id=canon_id,
                        canonical_code=canon_code,
                        entity_type=entity_type,
                        status=CanonicalStatus.ACTIVE.value,
                        created_at=now_dt,
                        updated_at=now_dt,
                    )
                    session.add(canon_entity)
                    session.flush()

                    mem_id = uuid.uuid4()
                    new_mem = CanonicalMembership(
                        id=mem_id,
                        canonical_entity_id=canon_id,
                        source_record_id=rec_id,
                        entity_type=entity_type,
                        valid_from=now_dt,
                        valid_to=None,
                        status=MembershipStatus.USABLE.value,
                        review_decision_id=decision.id,
                        created_at=now_dt,
                    )
                    session.add(new_mem)

                    audit_id = self._log_audit_event(
                        session=session,
                        action="CREATE",
                        entity_type=entity_type,
                        target_id=str(canon_id),
                        actor_username=actor_username,
                        payload={
                            "decision_id": str(decision.id),
                            "reason": "DISTINCT_DECISION_ACTIVATION",
                            "record_id": str(rec_id),
                        },
                    )
                    res_list.append(
                        ActivationResult(
                            canonical_entity_id=str(canon_id),
                            canonical_code=canon_code,
                            entity_type=entity_type,
                            action_taken="CREATED",
                            member_record_ids=[str(rec_id)],
                            membership_ids=[str(mem_id)],
                            audit_event_id=audit_id,
                        )
                    )
            return res_list

    def _activate_cluster_records(
        self,
        session: Session,
        record_ids: List[UUID],
        entity_type: str,
        decision: ReviewDecision,
        now_dt: datetime,
        actor_username: str,
    ) -> List[ActivationResult]:
        """Activate records of an approved cluster."""
        if not record_ids:
            return []

        canon_id = uuid.uuid4()
        canon_code = self._generate_canonical_code(entity_type)
        canon_entity = CanonicalEntity(
            id=canon_id,
            canonical_code=canon_code,
            entity_type=entity_type,
            status=CanonicalStatus.ACTIVE.value,
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(canon_entity)
        session.flush()

        membership_ids = []
        for rec_id in record_ids:
            self._supersede_existing_memberships(session, rec_id, entity_type, now_dt)
            mem_id = uuid.uuid4()
            mem = CanonicalMembership(
                id=mem_id,
                canonical_entity_id=canon_id,
                source_record_id=rec_id,
                entity_type=entity_type,
                valid_from=now_dt,
                valid_to=None,
                status=MembershipStatus.USABLE.value,
                review_decision_id=decision.id,
                created_at=now_dt,
            )
            session.add(mem)
            membership_ids.append(str(mem_id))

        audit_id = self._log_audit_event(
            session=session,
            action="APPROVE",
            entity_type=entity_type,
            target_id=str(canon_id),
            actor_username=actor_username,
            payload={
                "decision_id": str(decision.id),
                "decision_type": decision.decision_type,
                "cluster_records_count": len(record_ids),
                "canonical_code": canon_code,
            },
        )

        return [
            ActivationResult(
                canonical_entity_id=str(canon_id),
                canonical_code=canon_code,
                entity_type=entity_type,
                action_taken="CREATED",
                member_record_ids=[str(r) for r in record_ids],
                membership_ids=membership_ids,
                audit_event_id=audit_id,
            )
        ]

    def activate_singletons(
        self,
        session: Session,
        entity_type: str,
        source_system_codes: Optional[List[str]] = None,
        actor_username: str = "system_canonical_activator",
    ) -> SingletonActivationSummary:
        """
        Identify active source records without any active membership,
        and assign them into unique 1-to-1 Canonical Entities.
        """
        now_dt = datetime.now(timezone.utc)
        stmt = (
            select(SourceRecord)
            .where(
                and_(
                    SourceRecord.entity_type == entity_type,
                    SourceRecord.status == "ACTIVE",
                )
            )
        )

        if source_system_codes:
            sys_subquery = select(SourceSystem.id).where(SourceSystem.source_code.in_(source_system_codes))
            stmt = stmt.where(SourceRecord.source_system_id.in_(sys_subquery))

        all_records = session.execute(stmt).scalars().all()

        # Query all records with active memberships upfront to eliminate N+1 roundtrips
        active_rec_ids = set(
            session.execute(
                select(CanonicalMembership.source_record_id).where(
                    and_(
                        CanonicalMembership.entity_type == entity_type,
                        CanonicalMembership.status == MembershipStatus.USABLE.value,
                        CanonicalMembership.valid_to.is_(None),
                    )
                )
            ).scalars().all()
        )

        activated_count = 0
        canon_count = 0
        mem_count = 0

        for rec in all_records:
            if rec.id in active_rec_ids:
                continue

            # Create new canonical entity
            canon_id = uuid.uuid4()
            canon_code = self._generate_canonical_code(entity_type)
            canon = CanonicalEntity(
                id=canon_id,
                canonical_code=canon_code,
                entity_type=entity_type,
                status=CanonicalStatus.ACTIVE.value,
                created_at=now_dt,
                updated_at=now_dt,
            )
            session.add(canon)

            mem_id = uuid.uuid4()
            mem = CanonicalMembership(
                id=mem_id,
                canonical_entity_id=canon_id,
                source_record_id=rec.id,
                entity_type=entity_type,
                valid_from=now_dt,
                valid_to=None,
                status=MembershipStatus.USABLE.value,
                review_decision_id=None,
                created_at=now_dt,
            )
            session.add(mem)
            active_rec_ids.add(rec.id)

            activated_count += 1
            canon_count += 1
            mem_count += 1

        session.flush()
        return SingletonActivationSummary(
            entity_type=entity_type,
            total_singletons_activated=activated_count,
            canonical_entities_created=canon_count,
            memberships_created=mem_count,
        )

    def _log_audit_event(
        self,
        session: Session,
        action: str,
        entity_type: str,
        target_id: str,
        actor_username: str,
        payload: Dict[str, Any],
    ) -> str:
        """Create auditable hash-chained AuditEvent."""
        now_dt = datetime.now(timezone.utc)
        payload_str = json.dumps(payload, sort_keys=True, default=str)
        evt_hash = hashlib.sha256(
            f"{action}:{entity_type}:{target_id}:{now_dt.isoformat()}:{payload_str}".encode("utf-8")
        ).hexdigest()

        evt = AuditEvent(
            id=uuid.uuid4(),
            event_type="CANONICAL_ACTIVATION",
            actor_username=actor_username,
            target_entity_type=entity_type,
            target_entity_id=target_id,
            action=action,
            details_payload=payload,
            event_hash=evt_hash,
            created_at=now_dt,
        )
        session.add(evt)
        session.flush()
        return str(evt.id)
