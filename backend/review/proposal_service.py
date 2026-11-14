"""Maker Proposal Service for SongNhat CRM Review Workflow.

Sub-milestone: P2.4.4 - Maker Proposal & Decision Submission
Module: backend.review.proposal_service

Key Responsibilities:
1. Proposal Submission by Data Steward (Maker):
   - Submits formal proposals for 4 decision categories:
     * DUPLICATE (Same Entity)
     * RELATED (Related but Distinct with relationship type)
     * DISTINCT (Different Entities)
     * INSUFFICIENT_EVIDENCE (Needs additional evidence)
2. Conflict Signal & Evidence Guardrails:
   - Prohibits DUPLICATE proposal if severe Tax ID mismatch/conflict exists (BR-01 / BR-02).
   - Captures evidence snapshot (Positive, Negative, Neutral, Conflict signals).
3. Audit Trail & Cryptographic Chaining:
   - Emits PROPOSAL_SUBMITTED audit event with SHA-256 hash chaining.
   - Enforces Maker-Checker boundary: does NOT activate canonical membership at proposal step.
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
from backend.models.matching import CandidatePair, CandidatePairEvidence
from backend.models.review import CandidateCluster, ReviewTask, ReviewDecision

logger = logging.getLogger(__name__)


class ProposalDecisionType(str, Enum):
    DUPLICATE = "DUPLICATE"
    RELATED = "RELATED"
    DISTINCT = "DISTINCT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RelationshipType(str, Enum):
    PARENT_SUBSIDIARY = "PARENT_SUBSIDIARY"
    HEADQUARTERS_BRANCH = "HEADQUARTERS_BRANCH"
    COMPANY_AFFILIATION = "COMPANY_AFFILIATION"
    LEGAL_REPRESENTATIVE = "LEGAL_REPRESENTATIVE"


class ProposalSubmissionRequest(BaseModel):
    """Payload contract for submitting a Maker review proposal."""

    task_id: str
    decision_type: ProposalDecisionType
    decision_rationale: str = Field(min_length=5, description="Detailed business reason for proposal")
    relationship_type: Optional[RelationshipType] = None
    evidence_snapshot: Optional[Dict[str, Any]] = None


class ProposalView(BaseModel):
    """Active proposal information associated with a review task."""

    proposal_id: str
    task_id: str
    task_code: str
    proposer_id: str
    proposer_username: str
    decision_type: str
    relationship_type: Optional[str] = None
    decision_rationale: str
    evidence_snapshot: Optional[Dict[str, Any]] = None
    submitted_at: datetime


# ---------------------------------------------------------------------------
# Proposal Service Implementation
# ---------------------------------------------------------------------------

class ProposalService:
    """Service handling Maker proposal creation, validation, evidence linking, and audit."""

    def submit_proposal(
        self,
        session: Session,
        request: ProposalSubmissionRequest,
        proposer_user_id: Union[str, UUID],
        actor_username: str,
    ) -> ProposalView:
        """
        Submit a formal proposal for a ReviewTask by a Data Steward.
        Enforces:
        - Proposer role is DATA_STEWARD or ADMINISTRATOR.
        - Severe Tax ID conflict blocks DUPLICATE proposals.
        - Emits cryptographically chained PROPOSAL_SUBMITTED audit event.
        """
        t_uuid = UUID(str(request.task_id))
        p_uuid = UUID(str(proposer_user_id))

        task = session.execute(
            select(ReviewTask).where(ReviewTask.id == t_uuid)
        ).scalar_one_or_none()

        if not task:
            raise ValueError(f"ReviewTask '{request.task_id}' not found.")

        if task.status in ("RESOLVED", "CANCELLED"):
            raise ValueError(f"Cannot submit proposal: Task '{task.task_code}' is already {task.status}.")

        # Verify proposer has role DATA_STEWARD or ADMINISTRATOR
        roles = session.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == p_uuid)
        ).scalars().all()

        allowed_roles = {"DATA_STEWARD", "ADMINISTRATOR"}
        if not any(r in allowed_roles for r in roles):
            raise ValueError(
                f"Permission denied: User '{actor_username}' does not possess role DATA_STEWARD."
            )

        # Enforce severe conflict guardrail for DUPLICATE proposals
        if request.decision_type == ProposalDecisionType.DUPLICATE and task.candidate_pair_id:
            pair = session.execute(
                select(CandidatePair).where(CandidatePair.id == task.candidate_pair_id)
            ).scalar_one_or_none()

            if pair:
                # Check for severe negative/mismatch evidence on Tax ID
                mismatch_tax = session.execute(
                    select(CandidatePairEvidence)
                    .where(
                        and_(
                            CandidatePairEvidence.candidate_pair_id == pair.id,
                            CandidatePairEvidence.field_name == "TAX_ID",
                            CandidatePairEvidence.evidence_direction == "NEGATIVE",
                        )
                    )
                ).scalars().all()

                if mismatch_tax:
                    raise ValueError(
                        "Severe Tax ID Conflict Detected: Records have conflicting Tax Codes. "
                        "Proposal type DUPLICATE is prohibited by Business Rule BR-01. "
                        "Please select RELATED or DISTINCT."
                    )

        # If RELATED is selected, relationship_type must be specified
        if request.decision_type == ProposalDecisionType.RELATED and not request.relationship_type:
            raise ValueError("When proposing RELATED, relationship_type must be explicitly provided.")

        now_dt = datetime.now(timezone.utc)
        proposal_id = str(uuid.uuid4())

        # Update task status and assignment to proposer
        task.assigned_to = p_uuid
        task.status = "IN_PROGRESS"
        task.updated_at = now_dt

        # Construct evidence snapshot payload
        proposal_payload = {
            "proposal_id": proposal_id,
            "task_id": str(task.id),
            "task_code": task.task_code,
            "proposer_id": str(p_uuid),
            "proposer_username": actor_username,
            "decision_type": request.decision_type.value,
            "relationship_type": request.relationship_type.value if request.relationship_type else None,
            "decision_rationale": request.decision_rationale,
            "evidence_snapshot": request.evidence_snapshot or {},
            "submitted_at": now_dt.isoformat(),
        }

        # Log PROPOSAL_SUBMITTED audit event with SHA-256 hash chaining
        self._record_audit(
            session=session,
            action="PROPOSE",
            event_type="PROPOSAL_SUBMITTED",
            target_id=str(task.id),
            actor=actor_username,
            details=proposal_payload,
        )

        session.commit()

        return ProposalView(
            proposal_id=proposal_id,
            task_id=str(task.id),
            task_code=task.task_code,
            proposer_id=str(p_uuid),
            proposer_username=actor_username,
            decision_type=request.decision_type.value,
            relationship_type=request.relationship_type.value if request.relationship_type else None,
            decision_rationale=request.decision_rationale,
            evidence_snapshot=request.evidence_snapshot,
            submitted_at=now_dt,
        )

    def get_active_proposal(
        self,
        session: Session,
        task_id: Union[str, UUID],
    ) -> Optional[ProposalView]:
        """Fetch the latest active proposal submitted for a ReviewTask."""
        t_uuid = UUID(str(task_id))
        audit = session.execute(
            select(AuditEvent)
            .where(
                and_(
                    AuditEvent.target_entity_type == "review_tasks",
                    AuditEvent.target_entity_id == str(t_uuid),
                    AuditEvent.event_type == "PROPOSAL_SUBMITTED",
                )
            )
            .order_by(desc(AuditEvent.created_at))
            .limit(1)
        ).scalar_one_or_none()

        if not audit:
            return None

        details = audit.details_payload or {}
        return ProposalView(
            proposal_id=details.get("proposal_id", str(audit.id)),
            task_id=details.get("task_id", str(t_uuid)),
            task_code=details.get("task_code", ""),
            proposer_id=details.get("proposer_id", ""),
            proposer_username=details.get("proposer_username", audit.actor_username),
            decision_type=details.get("decision_type", "DUPLICATE"),
            relationship_type=details.get("relationship_type"),
            decision_rationale=details.get("decision_rationale", ""),
            evidence_snapshot=details.get("evidence_snapshot"),
            submitted_at=audit.created_at,
        )

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
                AuditEvent.target_entity_type == "review_tasks",
                AuditEvent.target_entity_id == target_id,
            )
            .order_by(desc(AuditEvent.created_at))
            .limit(1)
        ).scalar_one_or_none()

        evt_hash = generate_event_hash(
            previous_hash=last_event,
            event_type=event_type,
            action=action,
            target_type="review_tasks",
            target_id=target_id,
            timestamp_str=now_dt.isoformat(),
            payload=details,
        )

        audit_rec = AuditEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            actor_id=None,
            actor_username=actor,
            target_entity_type="review_tasks",
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
