"""Create Source & Intake schema

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. source_systems
    op.create_table(
        "source_systems",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("source_code", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("system_type", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("updated_at", ISOUtcDateTime, nullable=False),
        sa.Column("created_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("id", "entity_type", name="uq_source_sys_id_pool"),
        sa.CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_source_sys_pool"),
    )

    # 2. import_batches
    op.create_table(
        "import_batches",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("batch_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("source_system_id", GUIDType, sa.ForeignKey("source_systems.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("batch_type", sa.String(50), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_checksum", sa.String(64), nullable=False, index=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("total_rows_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows_quarantined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="RECEIVED"),
        sa.Column("extraction_at", ISOUtcDateTime, nullable=True),
        sa.Column("imported_at", ISOUtcDateTime, nullable=False),
        sa.Column("imported_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("source_system_id", "file_checksum", name="uq_batch_source_checksum"),
        sa.UniqueConstraint("id", "source_system_id", name="uq_import_batch_id_system"),
        sa.CheckConstraint("status IN ('RECEIVED', 'VALIDATING', 'COMPLETED', 'FAILED', 'QUARANTINED')", name="chk_batch_status"),
        sa.CheckConstraint(
            "(batch_type = 'UNMAPPED_QUARANTINE' AND source_system_id IS NULL) OR "
            "(batch_type <> 'UNMAPPED_QUARANTINE' AND source_system_id IS NOT NULL)",
            name="chk_batch_unmapped_source"
        ),
    )

    # 3. source_records
    op.create_table(
        "source_records",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("source_system_id", GUIDType, nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("source_key", sa.String(100), nullable=False, index=True),
        sa.Column("import_batch_id", GUIDType, sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("entity_subtype", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("record_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("updated_at", ISOUtcDateTime, nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id", "entity_type"],
            ["source_systems.id", "source_systems.entity_type"],
            name="fk_source_rec_system_pool",
            ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("source_system_id", "entity_type", "source_key", name="uq_source_entity_key"),
        sa.UniqueConstraint("id", "entity_type", name="uq_source_rec_id_pool"),
        sa.CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_source_rec_entity_type"),
    )

    # 4. source_record_versions
    op.create_table(
        "source_record_versions",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("source_record_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", GUIDType, sa.ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("row_anchor_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("effective_from", ISOUtcDateTime, nullable=False),
        sa.Column("effective_to", ISOUtcDateTime, nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("source_record_id", "version_number", name="uq_source_rec_version"),
        sa.CheckConstraint("version_number >= 1", name="chk_version_num_positive"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="chk_effective_range"),
    )

    # 5. batch_row_results
    op.create_table(
        "batch_row_results",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("import_batch_id", GUIDType, sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(100), nullable=True),
        sa.Column("row_status", sa.String(50), nullable=False, index=True),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        sa.Column("raw_row_hash", sa.String(64), nullable=False),
        sa.Column("raw_row_data", sa.JSON(), nullable=False),
        sa.Column("source_record_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("import_batch_id", "row_number", name="uq_batch_row_num"),
        sa.CheckConstraint("row_status IN ('MIGRATED', 'VALID', 'QUARANTINED', 'REJECTED')", name="chk_row_status"),
    )

    # 6. source_identifiers
    op.create_table(
        "source_identifiers",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("source_record_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("identifier_type", sa.String(50), nullable=False, index=True),
        sa.Column("identifier_value", sa.String(100), nullable=False, index=True),
        sa.Column("issuer", sa.String(100), nullable=True),
        sa.Column("jurisdiction", sa.String(50), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("entity_level", sa.String(50), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("source_record_id", "identifier_type", "identifier_value", name="uq_source_ident_exact"),
        sa.CheckConstraint(
            "identifier_type IN ('TAX_ID', 'PHONE', 'EMAIL', 'PASSPORT', 'NATIONAL_ID', 'WEBSITE', 'OTHER')",
            name="chk_ident_type"
        ),
    )

    # 7. matching_runs
    op.create_table(
        "matching_runs",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("run_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("entity_pool", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("policy_id", GUIDType, nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ceiling_breached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", ISOUtcDateTime, nullable=True),
        sa.Column("completed_at", ISOUtcDateTime, nullable=True),
        sa.Column("executed_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint("entity_pool IN ('ACCOUNT', 'CONTACT')", name="chk_match_run_pool"),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')", name="chk_match_run_status"),
    )

    # 8. run_sources
    op.create_table(
        "run_sources",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("matching_run_id", GUIDType, sa.ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("import_batch_id", GUIDType, nullable=False, index=True),
        sa.Column("source_system_id", GUIDType, nullable=False, index=True),
        sa.Column("snapshot_cutoff", ISOUtcDateTime, nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.ForeignKeyConstraint(
            ["import_batch_id", "source_system_id"],
            ["import_batches.id", "import_batches.source_system_id"],
            name="fk_run_sources_batch_system",
            ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("matching_run_id", "import_batch_id", name="uq_run_source_batch"),
    )

def downgrade() -> None:
    op.drop_table("run_sources")
    op.drop_table("matching_runs")
    op.drop_table("source_identifiers")
    op.drop_table("batch_row_results")
    op.drop_table("source_record_versions")
    op.drop_table("source_records")
    op.drop_table("import_batches")
    op.drop_table("source_systems")
