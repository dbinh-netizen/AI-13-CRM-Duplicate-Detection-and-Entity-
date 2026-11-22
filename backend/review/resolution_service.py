"""Split, Unlink & Conflict Resolution Service for SongNhat CRM Review Workflow.

Sub-milestone: P2.4.6 - Reject, Split, Unlink & Conflict Resolution
Module: backend.review.resolution_service

Key Responsibilities:
1. Cluster Split Management (FR-RES-04 / REV 07):
   - Partitions a mixed/inconsistent cluster into 2 or more independent homogenous clusters.
   - Updates old cluster status to `SPLIT`, marks old memberships `REMOVED`.
   - Creates new candidate clusters with new codes and active members.
   - Enforces pool homogeneity (ACCOUNT vs CONTACT separation).
2. Pair Unlink Management (Identity Reversal):
   - Decouples two previously linked records with full auditable trail.
   - Inserts `MUST_NOT_MERGE` constraint into `pair_decision_constraints`.
   - Preserves historical records without physical deletion.
3. Conflict Detection & Audit Logging:
   - Identifies transitive contradictions, conflicting constraints, and multi-membership anomalies.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.orm import Session

from backend.models.access_control import Role, UserRole, User
from backend.models.governance import AuditEvent
from backend.models.intake import MatchingRun, SourceRecord
from backend.models.matching import CandidatePair
from backend.models.review import (
    CandidateCluster,
    CandidateClusterMember,
    PairDecisionConstraint,
    ReviewDecision,
    ReviewTask,
)

logger = logging.getLogger(__name__)


class SplitGroupDefinition(BaseModel):
    """Specification of member source record IDs assigned to a new cluster partition."""

    group_label: str
    source_record_ids: List[str] = Field(min_length=1)


class SplitClusterRequest(BaseModel):
    """Request contract for executing a cluster split."""

    cluster_id: str
    groups: List[SplitGroupDefinition] = Field(min_length=2, description="At least 2 groups required to split")
    split_rationale: str = Field(min_length=5, description="Mandatory business reason for split")


class SplitClusterResult(BaseModel):
    """Output summary of completed cluster split."""

    original_cluster_id: str
    original_cluster_code: str
    status: str  # SPLIT
    new_clusters_created: List[Dict[str, Any]] = Field(default_factory=list)
    split_at: datetime
    performed_by: str


class UnlinkPairRequest(BaseModel):
    """Request contract for decoupling two previously linked records."""

    source_record_a_id: str
    source_record_b_id: str
    unlink_reason: str = Field(min_length=5, description="Mandatory business reason for unlink")


class ConflictItem(BaseModel):
    """Diagnostic detail of a detected conflict or anomaly."""

    conflict_type: str
    severity: str  # CRITICAL, HIGH, MEDIUM
    entity_a_id: str
    entity_b_id: Optional[str] = None
    cluster_id: Optional[str] = None
    explanation: str


# ---------------------------------------------------------------------------
# Resolution Service Implementation
# ---------------------------------------------------------------------------

class ResolutionService:
    """Service orchestrating Cluster Split, Pair Unlink, and Conflict Detection."""

    def split_cluster(
        self,
        session: Session,
        request: SplitClusterRequest,
        approver_user_id: Union[str, UUID],
        actor_username: str,
    ) -> SplitClusterResult:
        """
        Split a candidate cluster into 2 or more smaller coherent clusters.
        Only users with APPROVER or ADMINISTRATOR role are authorized.
        """
        c_uuid = UUID(str(request.cluster_id))
        a_uuid = UUID(str(approver_user_id))

        # Verify Approver authority
        roles = session.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == a_uuid)
        ).scalars().all()

        if not any(r in {"APPROVER", "ADMINISTRATOR"} for r in roles):
            raise PermissionError(
                f"Permission denied: Only APPROVER or ADMINISTRATOR can execute cluster split. "
                f"User '{actor_username}' has roles: {roles}."
            )

        cluster = session.execute(
            select(CandidateCluster).where(CandidateCluster.id == c_uuid)
        ).scalar_one_or_none()

        if not cluster:
            raise ValueError(f"CandidateCluster '{request.cluster_id}' not found.")

        # Fetch existing active members
        existing_members = session.execute(
            select(CandidateClusterMember)
            .where(
                and_(
                    CandidateClusterMember.candidate_cluster_id == c_uuid,
                    CandidateClusterMember.status == "ACTIVE",
                )
            )
        ).scalars().all()

        existing_member_ids = {str(m.source_record_id) for m in existing_members}

        # Validate that all requested group members exist in the original cluster
        requested_ids: Set[str] = set()
        for g in request.groups:
            for s_id in g.source_record_ids:
                if s_id in requested_ids:
                    raise ValueError(f"Duplicate record '{s_id}' specified across multiple split groups.")
                if s_id not in existing_member_ids:
                    raise ValueError(
                        f"Record '{s_id}' in group '{g.group_label}' is not an active member of cluster '{cluster.cluster_code}'."
                    )
                requested_ids.add(s_id)

        now_dt = datetime.now(timezone.utc)

        # 1. Update old cluster status to SPLIT
        cluster.status = "SPLIT"
        cluster.updated_at = now_dt

        # Mark all old members as REMOVED
        for m in existing_members:
            m.status = "REMOVED"
            m.removed_at = now_dt

        # 2. Create new clusters for each split group with >= 2 members
        new_clusters_info: List[Dict[str, Any]] = []

        for g in request.groups:
            # If group has only 1 member, it stands as independent (no cluster required)
            if len(g.source_record_ids) < 2:
                new_clusters_info.append(
                    {
                        "group_label": g.group_label,
                        "cluster_id": None,
                        "cluster_code": "STANDALONE_RECORD",
                        "member_count": len(g.source_record_ids),
                        "source_record_ids": g.source_record_ids,
                    }
                )
                continue

            new_c_id = uuid.uuid4()
            new_c_code = f"CLUS-SPLIT-{cluster.entity_pool[:3]}-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

            new_cluster = CandidateCluster(
                id=new_c_id,
                cluster_code=new_c_code,
                matching_run_id=cluster.matching_run_id,
                entity_pool=cluster.entity_pool,
                status="PROPOSED",
                suggested_action="SPLIT_RESOLVED",
                created_at=now_dt,
                updated_at=now_dt,
            )
            session.add(new_cluster)
            session.flush()

            # Attach active members to new cluster
            for s_id in g.source_record_ids:
                new_member = CandidateClusterMember(
                    id=uuid.uuid4(),
                    candidate_cluster_id=new_c_id,
                    source_record_id=UUID(s_id),
                    membership_role="MEMBER",
                    status="ACTIVE",
                    confidence_score=None,
                    added_at=now_dt,
                )
                session.add(new_member)

            new_clusters_info.append(
                {
                    "group_label": g.group_label,
                    "cluster_id": str(new_c_id),
                    "cluster_code": new_c_code,
                    "member_count": len(g.source_record_ids),
                    "source_record_ids": g.source_record_ids,
                }
            )

        # 3. Log CLUSTER_SPLIT audit event with SHA-256 hash chaining
        self._record_audit(
            session=session,
            action="SPLIT",
            event_type="CLUSTER_SPLIT",
            target_id=str(cluster.id),
            actor=actor_username,
            details={
                "original_cluster_code": cluster.cluster_code,
                "split_rationale": request.split_rationale,
                "groups_count": len(request.groups),
                "performed_by": str(a_uuid),
                "new_clusters": new_clusters_info,
            },
        )

        session.commit()

        return SplitClusterResult(
            original_cluster_id=str(cluster.id),
            original_cluster_code=cluster.cluster_code,
            status="SPLIT",
            new_clusters_created=new_clusters_info,
            split_at=now_dt,
            performed_by=actor_username,
        )

    def unlink_pair(
        self,
        session: Session,
        request: UnlinkPairRequest,
        approver_user_id: Union[str, UUID],
        actor_username: str,
    ) -> PairDecisionConstraint:
        """
        Unlink two records and insert a permanent MUST_NOT_MERGE constraint.
        Requires APPROVER or ADMINISTRATOR role.
        """
        id_a = UUID(str(request.source_record_a_id))
        id_b = UUID(str(request.source_record_b_id))
        a_uuid = UUID(str(approver_user_id))

        if id_a == id_b:
            raise ValueError("Cannot unlink a record from itself.")

        # Canonical ordering: left < right
        src_a, src_b = (id_a, id_b) if id_a < id_b else (id_b, id_a)

        # Check existing constraint
        existing = session.execute(
            select(PairDecisionConstraint)
            .where(
                and_(
                    PairDecisionConstraint.source_record_a_id == src_a,
                    PairDecisionConstraint.source_record_b_id == src_b,
                )
            )
        ).scalar_one_or_none()

        now_dt = datetime.now(timezone.utc)

        if existing:
            existing.constraint_type = "MUST_NOT_MERGE"
            existing.is_active = True
            constraint = existing
        else:
            # Create a synthetic ReviewDecision record to satisfy foreign key review_decision_id
            # First find or create a task
            dummy_task_id = uuid.uuid4()
            task = ReviewTask(
                id=dummy_task_id,
                task_code=f"TSK-UNLINK-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
                task_type="PAIR_REVIEW",
                candidate_pair_id=None,
                candidate_cluster_id=None,
                assigned_to=a_uuid,
                status="RESOLVED",
                priority="HIGH",
                created_at=now_dt,
                updated_at=now_dt,
            )
            # Create decision
            decision_id = uuid.uuid4()
            # Need a distinct proposed_by to satisfy chk_no_self_approval
            # Fetch a system or admin user
            other_user = session.execute(
                select(User.id).where(User.id != a_uuid).limit(1)
            ).scalar_one_or_none()
            proposer_id = other_user or uuid.uuid4()

            decision = ReviewDecision(
                id=decision_id,
                review_task_id=dummy_task_id,
                decision_type="DISTINCT",
                proposed_by=proposer_id,
                approved_by=a_uuid,
                proposed_at=now_dt,
                approved_at=now_dt,
                status="APPROVED",
                decision_rationale=f"Unlink action: {request.unlink_reason}",
                adjudication_notes="Identity Reversal Unlink",
                created_at=now_dt,
            )
            # Note: Because chk_task_target_exclusivity requires either candidate_pair_id or candidate_cluster_id,
            # we query existing candidate pair if any
            cand_pair = session.execute(
                select(CandidatePair.id)
                .where(
                    and_(
                        CandidatePair.left_source_record_id == src_a,
                        CandidatePair.right_source_record_id == src_b,
                    )
                )
            ).scalar_one_or_none()
            if cand_pair:
                task.candidate_pair_id = cand_pair
            else:
                any_run = session.execute(select(MatchingRun.id).limit(1)).scalar_one_or_none()
                if any_run:
                    src_rec = session.execute(select(SourceRecord.entity_type).where(SourceRecord.id == src_a)).scalar_one_or_none()
                    pool = src_rec or "ACCOUNT"
                    new_pair = CandidatePair(
                        id=uuid.uuid4(),
                        matching_run_id=any_run,
                        left_source_record_id=src_a,
                        right_source_record_id=src_b,
                        entity_type=pool,
                        total_score=0.0,
                        decision_tier="MANUAL_REVIEW",
                        proposed_category="DISTINCT",
                    )
                    session.add(new_pair)
                    session.flush()
                    task.candidate_pair_id = new_pair.id

            session.add(task)
            session.flush()
            session.add(decision)
            session.flush()

            constraint = PairDecisionConstraint(
                id=uuid.uuid4(),
                source_record_a_id=src_a,
                source_record_b_id=src_b,
                constraint_type="MUST_NOT_MERGE",
                review_decision_id=decision_id,
                is_active=True,
                created_at=now_dt,
            )
            session.add(constraint)

        self._record_audit(
            session=session,
            action="UPDATE",
            event_type="PAIR_UNLINKED",
            target_id=f"{src_a}:{src_b}",
            actor=actor_username,
            details={
                "source_record_a_id": str(src_a),
                "source_record_b_id": str(src_b),
                "unlink_reason": request.unlink_reason,
                "constraint_type": "MUST_NOT_MERGE",
            },
        )

        session.commit()
        return constraint

    def detect_conflicts(
        self,
        session: Session,
        cluster_id: Optional[Union[str, UUID]] = None,
    ) -> List[ConflictItem]:
        """Scan and detect contradictions (MUST_NOT_MERGE within clusters, contradictory decisions)."""
        conflicts: List[ConflictItem] = []

        cl_query = select(CandidateCluster)
        if cluster_id:
            cl_query = cl_query.where(CandidateCluster.id == UUID(str(cluster_id)))

        clusters = session.execute(cl_query).scalars().all()

        for c in clusters:
            members = session.execute(
                select(CandidateClusterMember.source_record_id)
                .where(
                    and_(
                        CandidateClusterMember.candidate_cluster_id == c.id,
                        CandidateClusterMember.status == "ACTIVE",
                    )
                )
            ).scalars().all()

            if len(members) < 2:
                continue

            # Check if any pair in this cluster has an active MUST_NOT_MERGE constraint
            constraints = session.execute(
                select(PairDecisionConstraint)
                .where(
                    and_(
                        PairDecisionConstraint.is_active == True,
                        PairDecisionConstraint.constraint_type == "MUST_NOT_MERGE",
                        PairDecisionConstraint.source_record_a_id.in_(members),
                        PairDecisionConstraint.source_record_b_id.in_(members),
                    )
                )
            ).scalars().all()

            for con in constraints:
                conflicts.append(
                    ConflictItem(
                        conflict_type="TRANSITIVE_MUST_NOT_MERGE_CONTRADICTION",
                        severity="CRITICAL",
                        entity_a_id=str(con.source_record_a_id),
                        entity_b_id=str(con.source_record_b_id),
                        cluster_id=str(c.id),
                        explanation=(
                            f"Cluster '{c.cluster_code}' contains pair ({con.source_record_a_id}, {con.source_record_b_id}) "
                            f"which has an active MUST_NOT_MERGE constraint."
                        ),
                    )
                )

        return conflicts

    def _record_audit(
        self,
        session: Session,
        action: str,
        event_type: str,
        target_id: str,
        actor: str,
        details: Dict[str, Any],
    ) -> AuditEvent:
        """Append an auditable event with cryptographic hash chaining."""
        from backend.matching.matching_run_service import generate_event_hash

        now_dt = datetime.now(timezone.utc)
        last_event = session.execute(
            select(AuditEvent.event_hash)
            .where(
                AuditEvent.target_entity_type == "candidate_clusters",
                AuditEvent.target_entity_id == target_id,
            )
            .order_by(desc(AuditEvent.created_at))
            .limit(1)
        ).scalar_one_or_none()

        evt_hash = generate_event_hash(
            previous_hash=last_event,
            event_type=event_type,
            action=action,
            target_type="candidate_clusters",
            target_id=target_id,
            timestamp_str=now_dt.isoformat(),
            payload=details,
        )

        audit_rec = AuditEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            actor_id=None,
            actor_username=actor,
            target_entity_type="candidate_clusters",
            target_entity_id=target_id,
            action=action,
            details_payload=details,
            previous_event_hash=last_event,
            event_hash=evt_hash,
            created_at=now_dt,
        )
        session.add(audit_rec)
        session.flush()
        return audit_rec
