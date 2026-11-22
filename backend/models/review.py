import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Text, Float, ForeignKey,
    CheckConstraint, UniqueConstraint, Index
)
from backend.models.base import Base, GUIDType, ISOUtcDateTime

class CandidateCluster(Base):
    __tablename__ = "candidate_clusters"
    __table_args__ = (
        CheckConstraint("status IN ('PROPOSED', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'SPLIT')", name="chk_cluster_status"),
        CheckConstraint("entity_pool IN ('ACCOUNT', 'CONTACT')", name="chk_cluster_pool"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    cluster_code = Column(String(100), unique=True, nullable=False, index=True)
    matching_run_id = Column(GUIDType, ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_pool = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="PROPOSED")
    suggested_action = Column(String(50), nullable=False)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class CandidateClusterMember(Base):
    __tablename__ = "candidate_cluster_members"
    __table_args__ = (
        UniqueConstraint("candidate_cluster_id", "source_record_id", name="uq_cluster_record_member"),
        # Partial unique index: A record can only be in one active candidate cluster at a time
        Index(
            "uq_single_active_cluster_member",
            "source_record_id",
            unique=True,
            postgresql_where=(Column("status") == "ACTIVE"),
            sqlite_where=(Column("status") == "ACTIVE")
        ),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    candidate_cluster_id = Column(GUIDType, ForeignKey("candidate_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    source_record_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True)
    membership_role = Column(String(50), nullable=False, default="MEMBER")
    status = Column(String(50), nullable=False, default="ACTIVE")
    confidence_score = Column(Float, nullable=True)
    added_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    removed_at = Column(ISOUtcDateTime, nullable=True)
    decision_id = Column(GUIDType, nullable=True)

class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint(
            "(candidate_pair_id IS NOT NULL AND candidate_cluster_id IS NULL) OR "
            "(candidate_pair_id IS NULL AND candidate_cluster_id IS NOT NULL)",
            name="chk_task_target_exclusivity"
        ),
        CheckConstraint("status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'ESCALATED', 'CANCELLED')", name="chk_task_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    task_code = Column(String(100), unique=True, nullable=False, index=True)
    task_type = Column(String(50), nullable=False)
    candidate_pair_id = Column(GUIDType, ForeignKey("candidate_pairs.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_cluster_id = Column(GUIDType, ForeignKey("candidate_clusters.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="OPEN")
    priority = Column(String(20), nullable=False, default="MEDIUM")
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("review_task_id", name="uq_review_task_decision"),
        CheckConstraint("proposed_by <> approved_by", name="chk_no_self_approval"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUPERSEDED')", name="chk_decision_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    review_task_id = Column(GUIDType, ForeignKey("review_tasks.id", ondelete="RESTRICT"), nullable=False, index=True)
    decision_type = Column(String(50), nullable=False)
    proposed_by = Column(GUIDType, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    approved_by = Column(GUIDType, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    proposed_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    status = Column(String(50), nullable=False, default="APPROVED")
    decision_rationale = Column(Text, nullable=False)
    adjudication_notes = Column(Text, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class PairDecisionConstraint(Base):
    __tablename__ = "pair_decision_constraints"
    __table_args__ = (
        UniqueConstraint("source_record_a_id", "source_record_b_id", name="uq_pair_constraint_endpoints"),
        CheckConstraint("source_record_a_id < source_record_b_id", name="chk_pair_constraint_order"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    source_record_a_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True)
    source_record_b_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True)
    constraint_type = Column(String(50), nullable=False, default="MUST_NOT_MERGE")
    review_decision_id = Column(GUIDType, ForeignKey("review_decisions.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
