"""Legacy staging rename and isolation

Revision ID: 0001
Revises: None
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. source_records -> legacy_source_records
    if "source_records" in existing_tables:
        op.rename_table("source_records", "legacy_source_records")
    elif "legacy_source_records" not in existing_tables:
        op.create_table(
            "legacy_source_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source_key", sa.String(100), nullable=False, index=True),
            sa.Column("source_system", sa.String(50), nullable=False, index=True),
            sa.Column("entity_type", sa.String(30), nullable=False),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("tax_code", sa.String(50), nullable=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("email", sa.String(150), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 2. candidate_pairs -> legacy_candidate_pairs
    if "candidate_pairs" in existing_tables:
        op.rename_table("candidate_pairs", "legacy_candidate_pairs")
    elif "legacy_candidate_pairs" not in existing_tables:
        op.create_table(
            "legacy_candidate_pairs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("left_source_key", sa.String(100), nullable=False, index=True),
            sa.Column("right_source_key", sa.String(100), nullable=False, index=True),
            sa.Column("entity_pool", sa.String(30), nullable=False),
            sa.Column("similarity_score", sa.Float(), nullable=True),
            sa.Column("proposed_category", sa.String(50), nullable=True),
            sa.Column("review_state", sa.String(50), nullable=True, default="NEW"),
            sa.Column("reasons", sa.Text(), nullable=True),
        )

    # 3. audit_logs -> legacy_audit_logs
    if "audit_logs" in existing_tables:
        op.rename_table("audit_logs", "legacy_audit_logs")
    elif "legacy_audit_logs" not in existing_tables:
        op.create_table(
            "legacy_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("action", sa.String(100), nullable=True),
            sa.Column("actor", sa.String(100), nullable=True),
            sa.Column("role", sa.String(50), nullable=True),
            sa.Column("target_pair", sa.String(150), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "legacy_source_records" in existing_tables and "source_records" not in existing_tables:
        op.rename_table("legacy_source_records", "source_records")
    if "legacy_candidate_pairs" in existing_tables and "candidate_pairs" not in existing_tables:
        op.rename_table("legacy_candidate_pairs", "candidate_pairs")
    if "legacy_audit_logs" in existing_tables and "audit_logs" not in existing_tables:
        op.rename_table("legacy_audit_logs", "audit_logs")
