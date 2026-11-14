"""RESTful API Endpoints for SongNhat CRM Review Workflow & Maker-Checker Engine.

Sub-milestones: P2.4.3, P2.4.4, P2.4.5, P2.4.6, P2.4.7
Module: backend.api.review_routes
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.review.approval_service import (
    AdjudicationAction,
    AdjudicationRequest,
    AdjudicationResultView,
    ApprovalService,
)
from backend.review.cluster_service import (
    ClusterDetailView,
    ClusterService,
    ClusterValidationResult,
)
from backend.review.proposal_service import (
    ProposalDecisionType,
    ProposalService,
    ProposalSubmissionRequest,
    ProposalView,
    RelationshipType,
)
from backend.review.queue_service import (
    QueueResponse,
    ReviewQueueService,
    TaskFilterParams,
    TaskSummaryView,
)
from backend.review.resolution_service import (
    ConflictItem,
    ResolutionService,
    SplitClusterRequest,
    SplitClusterResult,
    UnlinkPairRequest,
)
from backend.review.security import (
    UserContext,
    get_current_user,
    require_permission,
    require_role,
)

router = APIRouter(prefix="/api/review", tags=["Review Workflow & Maker-Checker Engine"])

queue_service = ReviewQueueService()
cluster_service = ClusterService()
proposal_service = ProposalService()
approval_service = ApprovalService(proposal_service=proposal_service, cluster_service=cluster_service)
resolution_service = ResolutionService()


# ---------------------------------------------------------------------------
# 1. Review Queue & Task Assignment Endpoints (P2.4.3)
# ---------------------------------------------------------------------------

@router.get("/queue", response_model=QueueResponse)
def get_review_queue(
    status_filter: Optional[str] = Query(None, alias="status"),
    task_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve filtered and paginated review task queue."""
    filters = TaskFilterParams(
        status=status_filter,
        task_type=task_type,
        priority=priority,
        assigned_to=assigned_to,
        page=page,
        limit=limit,
    )
    return queue_service.get_queue(db, filters)


@router.post("/tasks/{task_id}/assign")
def assign_review_task(
    task_id: str,
    user_id: Optional[str] = None,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign or claim review task for Data Steward (Optimistic Locking)."""
    # If user_id not provided, assign to self
    target_user_id = user_id or user.user_id
    try:
        task = queue_service.assign_task(
            session=db,
            task_id=task_id,
            user_id=target_user_id,
            actor_username=user.username,
        )
        return {"status": "SUCCESS", "task_id": str(task.id), "assigned_to": str(task.assigned_to)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/tasks/{task_id}/release")
def release_review_task(
    task_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Release claimed review task back to the OPEN queue."""
    try:
        task = queue_service.release_task(
            session=db,
            task_id=task_id,
            actor_username=user.username,
        )
        return {"status": "SUCCESS", "task_id": str(task.id), "task_status": task.status}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ---------------------------------------------------------------------------
# 2. Maker Proposal Submission Endpoints (P2.4.4)
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/proposal", response_model=ProposalView)
def submit_maker_proposal(
    task_id: str,
    request: ProposalSubmissionRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit formal decision proposal by Data Steward (Maker)."""
    if str(task_id) != str(request.task_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path task_id does not match payload task_id.")
    try:
        proposal = proposal_service.submit_proposal(
            session=db,
            request=request,
            proposer_user_id=user.user_id,
            actor_username=user.username,
        )
        return proposal
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/tasks/{task_id}/proposal", response_model=Optional[ProposalView])
def get_task_active_proposal(
    task_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get active pending proposal associated with a ReviewTask."""
    return proposal_service.get_active_proposal(db, task_id)


# ---------------------------------------------------------------------------
# 3. Independent Checker Approval Endpoints (P2.4.5)
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/adjudicate", response_model=AdjudicationResultView)
def adjudicate_checker_decision(
    task_id: str,
    request: AdjudicationRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Adjudicate a review task under strict Dual Control (Maker-Checker).
    Enforces that Approver is strictly distinct from Proposer (proposer <> approver).
    """
    if str(task_id) != str(request.task_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path task_id does not match payload task_id.")
    try:
        result = approval_service.adjudicate_task(
            session=db,
            request=request,
            approver_user_id=user.user_id,
            actor_username=user.username,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ---------------------------------------------------------------------------
# 4. Cluster Management, Split, Unlink & Conflict Endpoints (P2.4.2 & P2.4.6)
# ---------------------------------------------------------------------------

@router.get("/clusters/{cluster_id}", response_model=ClusterDetailView)
def get_cluster_details(
    cluster_id: str,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve comprehensive candidate cluster details and members."""
    try:
        return cluster_service.get_cluster_details(db, cluster_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResult)
def split_candidate_cluster(
    cluster_id: str,
    request: SplitClusterRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Split candidate cluster into multiple partitions (Approver only)."""
    if str(cluster_id) != str(request.cluster_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path cluster_id does not match payload cluster_id.")
    try:
        return resolution_service.split_cluster(
            session=db,
            request=request,
            approver_user_id=user.user_id,
            actor_username=user.username,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/pairs/unlink")
def unlink_candidate_pair(
    request: UnlinkPairRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unlink candidate records and insert permanent MUST_NOT_MERGE constraint."""
    try:
        constraint = resolution_service.unlink_pair(
            session=db,
            request=request,
            approver_user_id=user.user_id,
            actor_username=user.username,
        )
        return {
            "status": "SUCCESS",
            "constraint_id": str(constraint.id),
            "constraint_type": constraint.constraint_type,
            "source_record_a_id": str(constraint.source_record_a_id),
            "source_record_b_id": str(constraint.source_record_b_id),
        }
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/conflicts", response_model=List[ConflictItem])
def get_detected_conflicts(
    cluster_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve detected contradictions across candidate clusters."""
    return resolution_service.detect_conflicts(db, cluster_id=cluster_id)
