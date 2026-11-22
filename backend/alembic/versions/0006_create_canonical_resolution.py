"""Create Canonical Resolution schema

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. canonical_entities
    op.create_table(
        "canonical_entities",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("canonical_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("updated_at", ISOUtcDateTime, nullable=False),
        sa.Column("created_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("canonical_code", name="uq_canonical_code"),
        sa.UniqueConstraint("id", "entity_type", name="uq_canonical_id_pool"),
        sa.CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_canonical_pool"),
        sa.CheckConstraint("status IN ('ACTIVE', 'MERGED', 'SPLIT', 'ARCHIVED')", name="chk_canonical_status"),
    )

    # 2. canonical_memberships
    op.create_table(
        "canonical_memberships",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("canonical_entity_id", GUIDType, nullable=False, index=True),
        sa.Column("source_record_id", GUIDType, nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("valid_from", ISOUtcDateTime, nullable=False),
        sa.Column("valid_to", ISOUtcDateTime, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="USABLE", index=True),
        sa.Column("review_decision_id", GUIDType, sa.ForeignKey("review_decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_entity_id", "entity_type"],
            ["canonical_entities.id", "canonical_entities.entity_type"],
            name="fk_canon_mem_entity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id", "entity_type"],
            ["source_records.id", "source_records.entity_type"],
            name="fk_canon_mem_record",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_temporal_validity"),
        sa.CheckConstraint("status IN ('USABLE', 'HELD', 'SUPERSEDED', 'RETRACTED')", name="chk_membership_status"),
        sa.CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_canon_mem_pool"),
    )

    # 3. canonical_fields
    op.create_table(
        "canonical_fields",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("canonical_entity_id", GUIDType, sa.ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("field_name", sa.String(100), nullable=False, index=True),
        sa.Column("field_value", sa.Text(), nullable=True),
        sa.Column("valid_from", ISOUtcDateTime, nullable=False),
        sa.Column("valid_to", ISOUtcDateTime, nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_field_temporal_validity"),
    )

    # 4. canonical_field_provenance
    op.create_table(
        "canonical_field_provenance",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("canonical_field_id", GUIDType, sa.ForeignKey("canonical_fields.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_record_id", GUIDType, sa.ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("source_record_version_id", GUIDType, sa.ForeignKey("source_record_versions.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("source_field_name", sa.String(100), nullable=False),
        sa.Column("provenance_type", sa.String(50), nullable=False, server_default="DIRECT_SOURCE"),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint(
            "provenance_type IN ('DIRECT_SOURCE', 'STEWARD_OVERRIDE', 'AGGREGATED_RULE')",
            name="chk_provenance_type",
        ),
    )

    # 5. entity_relationships
    op.create_table(
        "entity_relationships",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("from_canonical_id", GUIDType, sa.ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("to_canonical_id", GUIDType, sa.ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("relationship_type", sa.String(50), nullable=False, index=True),
        sa.Column("valid_from", ISOUtcDateTime, nullable=False),
        sa.Column("valid_to", ISOUtcDateTime, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("review_decision_id", GUIDType, sa.ForeignKey("review_decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("from_canonical_id", "to_canonical_id", "relationship_type", "valid_from", name="uq_entity_relationship_edge"),
        sa.CheckConstraint("from_canonical_id <> to_canonical_id", name="chk_no_self_relationship"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_rel_temporal_validity"),
        sa.CheckConstraint("status IN ('ACTIVE', 'TERMINATED', 'DISPUTED')", name="chk_rel_status"),
    )

def downgrade() -> None:
    op.drop_table("entity_relationships")
    op.drop_table("canonical_field_provenance")
    op.drop_table("canonical_fields")
    op.drop_table("canonical_memberships")
    op.drop_table("canonical_entities")
