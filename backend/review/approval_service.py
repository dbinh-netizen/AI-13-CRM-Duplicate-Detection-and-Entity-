"""Independent Checker Approval Service for SongNhat CRM Review Workflow.

Sub-milestone: P2.4.5 - Independent Checker Approval (Dual Control)
Module: backend.review.approval_service

Key Responsibilities:
1. Strict Dual Control Enforcement:
   - Prohibits self-approval (`proposer_id <> approver_id` - REV 03 / BR-10).
   - Enforces Checker role: must possess role `APPROVER` or permission `DECISION_APPROVE`.
2. Adjudication Actions:
   - APPROVE: Formal approval, persists `ReviewDecision`, runs $O(K^2)$ cluster validation.
   - REJECT: Formal rejection, requires non-empty reason, creates `PairDecisionConstraint` ("MUST_NOT_MERGE").
   - REQUEST_MORE_EVIDENCE: Returns task to `ESCALATED` for further investigation.
3. Concurrency & Race Condition Protection:
   - Prevents duplicate approval when multiple Checkers adjudicate simultaneously (HTTP 409 Conflict).
4. Cryptographic Audit Event Chaining (SHA-256).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import Session

from backend.models.access_control import User, Role, UserRole
from backend.models.governance import AuditEvent
from backend.models.matching import CandidatePair
from backend.models.review import (
    CandidateCluster,
    CandidateClusterMember,
    PairDecisionConstraint,
    ReviewDecision,
    ReviewTask,
)
from backend.review.cluster_service import ClusterService
from backend.review.proposal_service import ProposalService, ProposalView
from backend.review.security import verify_independent_approver

logger = logging.getLogger(__name__)


class AdjudicationAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"


class AdjudicationRequest(BaseModel):
    """Payload contract for an Approver adjudicating a submitted proposal."""

    task_id: str
    action: AdjudicationAction
    adjudication_notes: Optional[str] = Field(default=None, description="Checker review notes")
    rejection_reason: Optional[str] = Field(default=None, description="Mandatory when action is REJECT")


class AdjudicationResultView(BaseModel):
    """View model for completed adjudication."""

    decision_id: Optional[str] = None
    task_id: str
    task_code: str
    action_taken: str
    status: str
    proposed_by: str
    approved_by: Optional[str] = None
    decision_type: str
    adjudication_notes: Optional[str] = None
    adjudicated_at: datetime


# ---------------------------------------------------------------------------
# Approval Service Implementation
# ---------------------------------------------------------------------------

class ApprovalService:
    """Service orchestrating Maker-Checker dual control verification and adjudication."""

    def __init__(
        self,
        proposal_service: Optional[ProposalService] = None,
        cluster_service: Optional[ClusterService] = None,
    ):
        self.proposal_service = proposal_service or ProposalService()
        self.cluster_service = cluster_service or ClusterService()

    def adjudicate_task(
        self,
        session: Session,
        request: AdjudicationRequest,
        approver_user_id: Union[str, UUID],
        actor_username: str,
    ) -> AdjudicationResultView:
        """
        Adjudicate a review task under strict Dual Control (Maker-Checker).
        Raises:
        - PermissionError: if self-approval is attempted or user lacks APPROVER role.
        - RuntimeError: on concurrent adjudication conflict.
        - ValueError: if task is invalid, proposal is missing, or cluster has transitive conflict.
        """
        t_uuid = UUID(str(request.task_id))
        a_uuid = UUID(str(approver_user_id))

        task = session.execute(
            select(ReviewTask).where(ReviewTask.id == t_uuid)
        ).scalar_one_or_none()

        if not task:
            raise ValueError(f"ReviewTask '{request.task_id}' not found.")

        if task.status in ("RESOLVED", "CANCELLED"):
            raise RuntimeError(
                f"Concurrent modification conflict: Task '{task.task_code}' has already been resolved or cancelled."
            )

        # 1. Fetch active proposal for this task
        proposal = self.proposal_service.get_active_proposal(session, t_uuid)
        if not proposal:
            raise ValueError(
                f"Cannot adjudicate: No active proposal submitted for task '{task.task_code}'. "
                "Data Steward must submit a proposal first."
            )

        proposer_uuid = UUID(proposal.proposer_id)

        # 2. STRICT MAKER-CHECKER ENFORCEMENT (REV 03 / BR-10 / SEC 01)
        if not verify_independent_approver(proposer_uuid, a_uuid):
            logger.warning(
                f"Security Guardrail Triggered: User '{actor_username}' attempted self-approval on task '{task.task_code}'."
            )
            raise PermissionError(
                "Self-approval is strictly prohibited by Business Rule BR-10 / REV 03. "
                "The Approver must be distinct from the Proposer."
            )

        # 3. Verify Approver Role
        approver_roles = session.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == a_uuid)
        ).scalars().all()

        allowed_roles = {"APPROVER", "ADMINISTRATOR"}
        if not any(r in allowed_roles for r in approver_roles):
            raise PermissionError(
                f"Permission denied: User '{actor_username}' does not possess role APPROVER."
            )

        # 4. Check for existing decision to prevent duplicate approval race condition
        existing_decision = session.execute(
            select(ReviewDecision).where(ReviewDecision.review_task_id == t_uuid)
        ).scalar_one_or_none()
        if existing_decision:
            raise RuntimeError(
                f"Race condition detected: ReviewTask '{task.task_code}' has already been adjudicated by another Approver."
            )

        now_dt = datetime.now(timezone.utc)

        # -------------------------------------------------------------------
        # Action: REQUEST_MORE_EVIDENCE
        # -------------------------------------------------------------------
        if request.action == AdjudicationAction.REQUEST_MORE_EVIDENCE:
            task.status = "ESCALATED"
            task.updated_at = now_dt

            self._record_audit(
                session=session,
                action="UPDATE",
                event_type="EVIDENCE_REQUESTED",
                target_id=str(task.id),
                actor=actor_username,
                details={
                    "task_code": task.task_code,
                    "approver_id": str(a_uuid),
                    "proposer_id": str(proposer_uuid),
                    "notes": request.adjudication_notes,
                },
            )
            session.commit()

            return AdjudicationResultView(
                decision_id=None,
                task_id=str(task.id),
                task_code=task.task_code,
                action_taken="REQUEST_MORE_EVIDENCE",
                status="ESCALATED",
                proposed_by=str(proposer_uuid),
                approved_by=str(a_uuid),
                decision_type=proposal.decision_type,
                adjudication_notes=request.adjudication_notes,
                adjudicated_at=now_dt,
            )

        # -------------------------------------------------------------------
        # Action: APPROVE
        # -------------------------------------------------------------------
        if request.action == AdjudicationAction.APPROVE:
            # If task is on a cluster and proposal is DUPLICATE, run O(K^2) Graph Validation
            if task.candidate_cluster_id and proposal.decision_type == "DUPLICATE":
                val_result = self.cluster_service.validate_cluster_transitive_consistency(
                    session=session,
                    cluster_id=task.candidate_cluster_id,
                )
                if not val_result.is_valid:
                    raise ValueError(
                        f"Cannot approve cluster: Transitive contradiction detected. "
                        f"Reasons: {'; '.join(val_result.reasons)}"
                    )

            decision_id = uuid.uuid4()
            decision = ReviewDecision(
                id=decision_id,
                review_task_id=t_uuid,
                decision_type=proposal.decision_type,
                proposed_by=proposer_uuid,
                approved_by=a_uuid,
                proposed_at=proposal.submitted_at,
                approved_at=now_dt,
                status="APPROVED",
                decision_rationale=proposal.decision_rationale,
                adjudication_notes=request.adjudication_notes,
                created_at=now_dt,
            )
            session.add(decision)

            # Update task status
            task.status = "RESOLVED"
            task.updated_at = now_dt

            # Update cluster status if cluster task
            if task.candidate_cluster_id:
                cluster = session.execute(
                    select(CandidateCluster).where(CandidateCluster.id == task.candidate_cluster_id)
                ).scalar_one_or_none()
                if cluster:
                    cluster.status = "APPROVED"
                    cluster.updated_at = now_dt

            # Audit event
            self._record_audit(
                session=session,
                action="APPROVE",
                event_type="DECISION_APPROVED",
                target_id=str(decision_id),
                actor=actor_username,
                details={
                    "task_code": task.task_code,
                    "decision_type": proposal.decision_type,
                    "proposed_by": str(proposer_uuid),
                    "approved_by": str(a_uuid),
                    "status": "APPROVED",
                },
            )

            session.commit()

            return AdjudicationResultView(
                decision_id=str(decision_id),
                task_id=str(task.id),
                task_code=task.task_code,
                action_taken="APPROVE",
                status="APPROVED",
                proposed_by=str(proposer_uuid),
                approved_by=str(a_uuid),
                decision_type=proposal.decision_type,
                adjudication_notes=request.adjudication_notes,
                adjudicated_at=now_dt,
            )

        # -------------------------------------------------------------------
        # Action: REJECT
        # -------------------------------------------------------------------
        if request.action == AdjudicationAction.REJECT:
            if not request.rejection_reason or len(request.rejection_reason.strip()) < 5:
                raise ValueError("When rejecting a proposal, a detailed rejection_reason is mandatory.")

            decision_id = uuid.uuid4()
            decision = ReviewDecision(
                id=decision_id,
                review_task_id=t_uuid,
                decision_type=proposal.decision_type,
                proposed_by=proposer_uuid,
                approved_by=a_uuid,
                proposed_at=proposal.submitted_at,
                approved_at=now_dt,
                status="REJECTED",
                decision_rationale=proposal.decision_rationale,
                adjudication_notes=f"REJECTED: {request.rejection_reason}. {request.adjudication_notes or ''}".strip(),
                created_at=now_dt,
            )
            session.add(decision)
            session.flush()

            # Create MUST_NOT_MERGE constraint for candidate pair
            if task.candidate_pair_id:
                pair = session.execute(
                    select(CandidatePair).where(CandidatePair.id == task.candidate_pair_id)
                ).scalar_one_or_none()

                if pair:
                    left_id = pair.left_source_record_id
                    right_id = pair.right_source_record_id
                    src_a, src_b = (left_id, right_id) if left_id < right_id else (right_id, left_id)

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

            # Update task status
            task.status = "RESOLVED"
            task.updated_at = now_dt

            # Update cluster status if cluster task
            if task.candidate_cluster_id:
                cluster = session.execute(
                    select(CandidateCluster).where(CandidateCluster.id == task.candidate_cluster_id)
                ).scalar_one_or_none()
                if cluster:
                    cluster.status = "REJECTED"
                    cluster.updated_at = now_dt

            # Audit event
            self._record_audit(
                session=session,
                action="REJECT",
                event_type="DECISION_REJECTED",
                target_id=str(decision_id),
                actor=actor_username,
                details={
                    "task_code": task.task_code,
                    "decision_type": proposal.decision_type,
                    "proposed_by": str(proposer_uuid),
                    "approved_by": str(a_uuid),
                    "rejection_reason": request.rejection_reason,
                    "status": "REJECTED",
                },
            )

            session.commit()

            return AdjudicationResultView(
                decision_id=str(decision_id),
                task_id=str(task.id),
                task_code=task.task_code,
                action_taken="REJECT",
                status="REJECTED",
                proposed_by=str(proposer_uuid),
                approved_by=str(a_uuid),
                decision_type=proposal.decision_type,
                adjudication_notes=decision.adjudication_notes,
                adjudicated_at=now_dt,
            )

        raise ValueError(f"Unsupported adjudication action: {request.action}")

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
                AuditEvent.target_entity_type == "review_decisions",
                AuditEvent.target_entity_id == target_id,
            )
            .order_by(desc(AuditEvent.created_at))
            .limit(1)
        ).scalar_one_or_none()

        evt_hash = generate_event_hash(
            previous_hash=last_event,
            event_type=event_type,
            action=action,
            target_type="review_decisions",
            target_id=target_id,
            timestamp_str=now_dt.isoformat(),
            payload=details,
        )

        audit_rec = AuditEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            actor_id=None,
            actor_username=actor,
            target_entity_type="review_decisions",
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
