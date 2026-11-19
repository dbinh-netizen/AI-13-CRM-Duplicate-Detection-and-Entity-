"""Create Cluster & Review schema

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. candidate_clusters
    op.create_table(
        "candidate_clusters",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("cluster_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("matching_run_id", GUIDType, sa.ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("entity_pool", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="PROPOSED"),
        sa.Column("suggested_action", sa.String(50), nullable=False),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("updated_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint("status IN ('PROPOSED', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'SPLIT')", name="chk_cluster_status"),
        sa.CheckConstraint("entity_pool IN ('ACCOUNT', 'CONTACT')", name="chk_cluster_pool"),
    )

    # 2. candidate_cluster_members
    op.create_table(
        "candidate_cluster_members",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("candidate_cluster_id", GUIDType, sa.ForeignKey("candidate_clusters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_record_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("membership_role", sa.String(50), nullable=False, server_default="MEMBER"),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("added_at", ISOUtcDateTime, nullable=False),
        sa.Column("removed_at", ISOUtcDateTime, nullable=True),
        sa.Column("decision_id", GUIDType, nullable=True),
        sa.UniqueConstraint("candidate_cluster_id", "source_record_id", name="uq_cluster_record_member"),
    )
    op.create_index(
        "uq_single_active_cluster_member",
        "candidate_cluster_members",
        ["source_record_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    # 3. review_tasks
    op.create_table(
        "review_tasks",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("task_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("candidate_pair_id", GUIDType, sa.ForeignKey("candidate_pairs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("candidate_cluster_id", GUIDType, sa.ForeignKey("candidate_clusters.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("assigned_to", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="OPEN"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="MEDIUM"),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("updated_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint(
            "(candidate_pair_id IS NOT NULL AND candidate_cluster_id IS NULL) OR "
            "(candidate_pair_id IS NULL AND candidate_cluster_id IS NOT NULL)",
            name="chk_task_target_exclusivity",
        ),
        sa.CheckConstraint("status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'ESCALATED', 'CANCELLED')", name="chk_task_status"),
    )

    # 4. review_decisions
    op.create_table(
        "review_decisions",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("review_task_id", GUIDType, sa.ForeignKey("review_tasks.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("decision_type", sa.String(50), nullable=False),
        sa.Column("proposed_by", GUIDType, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("approved_by", GUIDType, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("proposed_at", ISOUtcDateTime, nullable=False),
        sa.Column("approved_at", ISOUtcDateTime, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="APPROVED"),
        sa.Column("decision_rationale", sa.Text(), nullable=False),
        sa.Column("adjudication_notes", sa.Text(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("review_task_id", name="uq_review_task_decision"),
        sa.CheckConstraint("proposed_by <> approved_by", name="chk_no_self_approval"),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUPERSEDED')", name="chk_decision_status"),
    )

    # 5. pair_decision_constraints
    op.create_table(
        "pair_decision_constraints",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("source_record_a_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_record_b_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("constraint_type", sa.String(50), nullable=False, server_default="MUST_NOT_MERGE"),
        sa.Column("review_decision_id", GUIDType, sa.ForeignKey("review_decisions.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("source_record_a_id", "source_record_b_id", name="uq_pair_constraint_endpoints"),
        sa.CheckConstraint("source_record_a_id < source_record_b_id", name="chk_pair_constraint_order"),
    )

def downgrade() -> None:
    op.drop_table("pair_decision_constraints")
    op.drop_table("review_decisions")
    op.drop_table("review_tasks")
    op.drop_index("uq_single_active_cluster_member", table_name="candidate_cluster_members")
    op.drop_table("candidate_cluster_members")
    op.drop_table("candidate_clusters")
