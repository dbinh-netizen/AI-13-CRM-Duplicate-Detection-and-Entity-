"""Create Governance & Export schema

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("actor_id", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("actor_username", sa.String(100), nullable=False),
        sa.Column("target_entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("target_entity_id", sa.String(100), nullable=False, index=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("details_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False, index=True),
        sa.Column("is_migrated_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hash_generated_at_migration", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False, index=True),
        sa.CheckConstraint(
            "action IN ('CREATE', 'UPDATE', 'DELETE', 'PROPOSE', 'APPROVE', 'REJECT', 'SPLIT', 'MERGE', 'EXPORT', 'LOGIN')",
            name="chk_audit_action",
        ),
    )

    # 2. retention_policies
    op.create_table(
        "retention_policies",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("policy_name", sa.String(100), nullable=False),
        sa.Column("target_table", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("action_on_expiry", sa.String(50), nullable=False, server_default="SOFT_DELETE"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("created_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("target_table", "entity_type", name="uq_retention_policy_target"),
        sa.CheckConstraint("retention_days > 0", name="chk_retention_period_positive"),
    )

    # 3. deletion_ledger
    op.create_table(
        "deletion_ledger",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("target_table", sa.String(100), nullable=False),
        sa.Column("original_record_id", sa.String(100), nullable=False, index=True),
        sa.Column("deletion_reason", sa.Text(), nullable=False),
        sa.Column("authorized_by", GUIDType, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("compliance_regulation", sa.String(100), nullable=False, server_default="GDPR_RTBF"),
        sa.Column("tombstone_payload", sa.JSON(), nullable=True),
        sa.Column("deleted_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("target_table", "original_record_id", name="uq_deletion_record_target"),
    )

    # 4. export_jobs
    op.create_table(
        "export_jobs",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("job_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("export_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("filter_criteria", sa.JSON(), nullable=True),
        sa.Column("total_items_exported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_path", sa.String(255), nullable=True),
        sa.Column("file_checksum", sa.String(64), nullable=True),
        sa.Column("requested_by", GUIDType, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("started_at", ISOUtcDateTime, nullable=True),
        sa.Column("completed_at", ISOUtcDateTime, nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("job_code", name="uq_export_jobs_code"),
        sa.CheckConstraint("status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')", name="chk_export_status"),
    )

    # 5. export_manifest_items
    op.create_table(
        "export_manifest_items",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("export_job_id", GUIDType, sa.ForeignKey("export_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("canonical_membership_id", GUIDType, sa.ForeignKey("canonical_memberships.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("source_record_id", GUIDType, nullable=False, index=True),
        sa.Column("canonical_entity_id", GUIDType, nullable=False, index=True),
        sa.Column("is_superseded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("export_job_id", "canonical_membership_id", name="uq_export_job_item"),
    )

def downgrade() -> None:
    op.drop_table("export_manifest_items")
    op.drop_table("export_jobs")
    op.drop_table("deletion_ledger")
    op.drop_table("retention_policies")
    op.drop_table("audit_events")
