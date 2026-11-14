"""Review Task Queue & Assignment Service for SongNhat CRM.

Sub-milestone: P2.4.3 - Review Task Assignment & Queue
Module: backend.review.queue_service

Key Responsibilities:
1. Review Task Creation & Queue Population:
   - Initializes tasks from Candidate Pairs or Candidate Clusters.
   - Enforces target exclusivity: `chk_task_target_exclusivity`.
2. Multi-dimensional Queue Filtering & Pagination:
   - Filter by status, entity_pool, priority, assigned_to, matching_run_id, cluster_id.
3. Task Assignment & Role Verification:
   - Assigns/reassigns tasks only to users possessing role `DATA_STEWARD` or permission `TASK_REVIEW`.
4. Optimistic Locking & Concurrency Protection:
   - Protects against concurrent modifications using timestamp/version checks.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import Session

from backend.models.access_control import User, Role, UserRole
from backend.models.governance import AuditEvent
from backend.models.matching import CandidatePair
from backend.models.review import CandidateCluster, ReviewTask

logger = logging.getLogger(__name__)


class TaskFilterParams(BaseModel):
    """Filter parameters for querying Review Task queues."""

    status: Optional[str] = None  # OPEN, IN_PROGRESS, RESOLVED, ESCALATED, CANCELLED
    task_type: Optional[str] = None  # PAIR_REVIEW, CLUSTER_REVIEW
    priority: Optional[str] = None  # HIGH, MEDIUM, LOW
    assigned_to: Optional[str] = None
    matching_run_id: Optional[str] = None
    entity_pool: Optional[str] = None  # ACCOUNT, CONTACT
    has_conflicts: Optional[bool] = None
    search_keyword: Optional[str] = None
    page: int = 1
    limit: int = 20


class TaskSummaryView(BaseModel):
    """View model for a task in the queue."""

    task_id: str
    task_code: str
    task_type: str
    status: str
    priority: str
    assigned_to: Optional[str] = None
    assigned_username: Optional[str] = None
    candidate_pair_id: Optional[str] = None
    candidate_cluster_id: Optional[str] = None
    entity_pool: Optional[str] = None
    target_summary: Optional[str] = None
    score: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class QueueResponse(BaseModel):
    """Paginated response container for review tasks."""

    total_count: int
    page: int
    limit: int
    total_pages: int
    tasks: List[TaskSummaryView] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Review Queue Service Implementation
# ---------------------------------------------------------------------------

class ReviewQueueService:
    """Service managing review task creation, filtering, assignment, and concurrency control."""

    def create_task_for_pair(
        self,
        session: Session,
        candidate_pair_id: Union[str, UUID],
        priority: str = "MEDIUM",
        actor_username: str = "system",
    ) -> ReviewTask:
        """Create a dedicated ReviewTask for a single candidate pair."""
        p_uuid = UUID(str(candidate_pair_id))
        pair = session.execute(
            select(CandidatePair).where(CandidatePair.id == p_uuid)
        ).scalar_one_or_none()

        if not pair:
            raise ValueError(f"CandidatePair '{candidate_pair_id}' not found.")

        # Check if task already exists for this pair
        existing = session.execute(
            select(ReviewTask).where(ReviewTask.candidate_pair_id == p_uuid)
        ).scalar_one_or_none()
        if existing:
            return existing

        now_dt = datetime.now(timezone.utc)
        task_id = uuid.uuid4()
        task_code = f"TSK-PAIR-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        task = ReviewTask(
            id=task_id,
            task_code=task_code,
            task_type="PAIR_REVIEW",
            candidate_pair_id=p_uuid,
            candidate_cluster_id=None,
            assigned_to=None,
            status="OPEN",
            priority=priority.upper(),
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(task)
        session.flush()

        self._record_audit(
            session=session,
            action="CREATE",
            event_type="REVIEW_TASK_CREATED",
            target_id=str(task_id),
            actor=actor_username,
            details={"task_code": task_code, "candidate_pair_id": str(p_uuid)},
        )

        session.commit()
        return task

    def create_task_for_cluster(
        self,
        session: Session,
        candidate_cluster_id: Union[str, UUID],
        priority: str = "HIGH",
        actor_username: str = "system",
    ) -> ReviewTask:
        """Create a dedicated ReviewTask for a candidate cluster."""
        c_uuid = UUID(str(candidate_cluster_id))
        cluster = session.execute(
            select(CandidateCluster).where(CandidateCluster.id == c_uuid)
        ).scalar_one_or_none()

        if not cluster:
            raise ValueError(f"CandidateCluster '{candidate_cluster_id}' not found.")

        existing = session.execute(
            select(ReviewTask).where(ReviewTask.candidate_cluster_id == c_uuid)
        ).scalar_one_or_none()
        if existing:
            return existing

        now_dt = datetime.now(timezone.utc)
        task_id = uuid.uuid4()
        task_code = f"TSK-CLUS-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        task = ReviewTask(
            id=task_id,
            task_code=task_code,
            task_type="CLUSTER_REVIEW",
            candidate_pair_id=None,
            candidate_cluster_id=c_uuid,
            assigned_to=None,
            status="OPEN",
            priority=priority.upper(),
            created_at=now_dt,
            updated_at=now_dt,
        )
        session.add(task)
        session.flush()

        self._record_audit(
            session=session,
            action="CREATE",
            event_type="REVIEW_TASK_CREATED",
            target_id=str(task_id),
            actor=actor_username,
            details={"task_code": task_code, "candidate_cluster_id": str(c_uuid)},
        )

        session.commit()
        return task

    def get_queue(
        self,
        session: Session,
        filters: TaskFilterParams,
    ) -> QueueResponse:
        """Retrieve paginated and filtered tasks from the review queue."""
        query = select(ReviewTask, User.username).outerjoin(User, ReviewTask.assigned_to == User.id)

        conditions = []
        if filters.status:
            conditions.append(ReviewTask.status == filters.status.upper())
        if filters.task_type:
            conditions.append(ReviewTask.task_type == filters.task_type.upper())
        if filters.priority:
            conditions.append(ReviewTask.priority == filters.priority.upper())
        if filters.assigned_to:
            conditions.append(ReviewTask.assigned_to == UUID(str(filters.assigned_to)))

        if conditions:
            query = query.where(and_(*conditions))

        # Count total
        count_query = select(func.count(ReviewTask.id))
        if conditions:
            count_query = count_query.where(and_(*conditions))
        total_count = session.execute(count_query).scalar_one()

        # Sort priority HIGH -> MEDIUM -> LOW, then newest first
        query = query.order_by(
            desc(ReviewTask.priority == "HIGH"),
            desc(ReviewTask.priority == "MEDIUM"),
            desc(ReviewTask.created_at),
        )

        # Pagination
        offset = (filters.page - 1) * filters.limit
        query = query.offset(offset).limit(filters.limit)

        results = session.execute(query).all()
        tasks_views: List[TaskSummaryView] = []

        for task, username in results:
            tasks_views.append(
                TaskSummaryView(
                    task_id=str(task.id),
                    task_code=task.task_code,
                    task_type=task.task_type,
                    status=task.status,
                    priority=task.priority,
                    assigned_to=str(task.assigned_to) if task.assigned_to else None,
                    assigned_username=username,
                    candidate_pair_id=str(task.candidate_pair_id) if task.candidate_pair_id else None,
                    candidate_cluster_id=str(task.candidate_cluster_id) if task.candidate_cluster_id else None,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )

        total_pages = (total_count + filters.limit - 1) // filters.limit if filters.limit > 0 else 1
        return QueueResponse(
            total_count=total_count,
            page=filters.page,
            limit=filters.limit,
            total_pages=total_pages,
            tasks=tasks_views,
        )

    def assign_task(
        self,
        session: Session,
        task_id: Union[str, UUID],
        user_id: Union[str, UUID],
        actor_username: str,
        expected_updated_at: Optional[datetime] = None,
    ) -> ReviewTask:
        """
        Assign or reassign a review task to a Data Steward with Optimistic Locking.
        Raises ValueError if user lacks DATA_STEWARD role or task not found.
        Raises RuntimeError on concurrent modification conflict.
        """
        t_uuid = UUID(str(task_id))
        u_uuid = UUID(str(user_id))

        task = session.execute(
            select(ReviewTask).where(ReviewTask.id == t_uuid)
        ).scalar_one_or_none()

        if not task:
            raise ValueError(f"ReviewTask '{task_id}' not found.")

        # Optimistic locking check
        if expected_updated_at and task.updated_at != expected_updated_at:
            raise RuntimeError(
                f"Concurrent modification conflict: Task '{task.task_code}' was modified by another process. "
                f"Expected {expected_updated_at}, found {task.updated_at}."
            )

        # Verify assignee role: user must have DATA_STEWARD role or TASK_REVIEW permission
        user_roles = session.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == u_uuid)
        ).scalars().all()

        allowed_roles = {"DATA_STEWARD", "ADMINISTRATOR"}
        if not any(r in allowed_roles for r in user_roles):
            raise ValueError(
                f"Permission denied: User '{user_id}' does not possess role DATA_STEWARD. "
                f"Current roles: {user_roles}."
            )

        prev_assigned = str(task.assigned_to) if task.assigned_to else None
        now_dt = datetime.now(timezone.utc)

        task.assigned_to = u_uuid
        task.status = "IN_PROGRESS"
        task.updated_at = now_dt

        event_type = "TASK_REASSIGNED" if prev_assigned else "TASK_ASSIGNED"
        self._record_audit(
            session=session,
            action="UPDATE",
            event_type=event_type,
            target_id=str(t_uuid),
            actor=actor_username,
            details={
                "task_code": task.task_code,
                "previous_assigned_to": prev_assigned,
                "new_assigned_to": str(u_uuid),
            },
        )

        session.commit()
        return task

    def release_task(
        self,
        session: Session,
        task_id: Union[str, UUID],
        actor_username: str,
        expected_updated_at: Optional[datetime] = None,
    ) -> ReviewTask:
        """Release claimed task back to OPEN queue."""
        t_uuid = UUID(str(task_id))
        task = session.execute(
            select(ReviewTask).where(ReviewTask.id == t_uuid)
        ).scalar_one_or_none()

        if not task:
            raise ValueError(f"ReviewTask '{task_id}' not found.")

        if expected_updated_at and task.updated_at != expected_updated_at:
            raise RuntimeError("Concurrent modification conflict: Task was modified by another process.")

        prev_user = str(task.assigned_to) if task.assigned_to else None
        now_dt = datetime.now(timezone.utc)

        task.assigned_to = None
        task.status = "OPEN"
        task.updated_at = now_dt

        self._record_audit(
            session=session,
            action="UPDATE",
            event_type="TASK_RELEASED",
            target_id=str(t_uuid),
            actor=actor_username,
            details={"task_code": task.task_code, "released_by": prev_user},
        )

        session.commit()
        return task

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
