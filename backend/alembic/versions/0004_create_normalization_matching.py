"""Create Normalization & Matching schema

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. normalization_policies
    op.create_table(
        "normalization_policies",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("policy_name", sa.String(100), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="DRAFT"),
        sa.Column("config_payload", sa.JSON(), nullable=False),
        sa.Column("effective_from", ISOUtcDateTime, nullable=False),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("created_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("policy_name", "version_number", name="uq_policy_version"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="chk_policy_status"),
    )

    # 2. normalized_features
    op.create_table(
        "normalized_features",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("source_record_version_id", GUIDType, sa.ForeignKey("source_record_versions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("policy_id", GUIDType, sa.ForeignKey("normalization_policies.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("feature_name", sa.String(100), nullable=False, index=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("tokens_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("source_record_version_id", "policy_id", "feature_name", name="uq_norm_feature_version"),
    )

    # 3. candidate_pairs
    op.create_table(
        "candidate_pairs",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("matching_run_id", GUIDType, sa.ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("left_source_record_id", GUIDType, nullable=False, index=True),
        sa.Column("right_source_record_id", GUIDType, nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("decision_tier", sa.String(50), nullable=False),
        sa.Column("proposed_category", sa.String(50), nullable=False),
        sa.Column("legacy_pair_id", sa.Integer(), nullable=True, index=True),
        sa.Column("legacy_reasons_raw", sa.Text(), nullable=True),
        sa.Column("is_migrated_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.ForeignKeyConstraint(
            ["left_source_record_id", "entity_type"],
            ["source_records.id", "source_records.entity_type"],
            name="fk_cand_pair_left_pool",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["right_source_record_id", "entity_type"],
            ["source_records.id", "source_records.entity_type"],
            name="fk_cand_pair_right_pool",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("matching_run_id", "left_source_record_id", "right_source_record_id", name="uq_cand_pair_run"),
        sa.UniqueConstraint("legacy_pair_id", name="uq_cand_pair_legacy_id"),
        sa.CheckConstraint("left_source_record_id < right_source_record_id", name="chk_cand_pair_order"),
        sa.CheckConstraint("total_score >= 0.0 AND total_score <= 100.0", name="chk_cand_score_range"),
        sa.CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_cand_pair_pool"),
    )

    # 4. candidate_blocking_paths
    op.create_table(
        "candidate_blocking_paths",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("candidate_pair_id", GUIDType, sa.ForeignKey("candidate_pairs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("blocking_key_name", sa.String(100), nullable=False, index=True),
        sa.Column("blocking_value", sa.String(255), nullable=False, index=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.UniqueConstraint("candidate_pair_id", "blocking_key_name", "blocking_value", name="uq_cand_block_path"),
    )

    # 5. candidate_pair_evidence
    op.create_table(
        "candidate_pair_evidence",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("candidate_pair_id", GUIDType, sa.ForeignKey("candidate_pairs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_name", sa.String(100), nullable=False),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("left_raw_value", sa.Text(), nullable=True),
        sa.Column("right_raw_value", sa.Text(), nullable=True),
        sa.Column("left_normalized_value", sa.Text(), nullable=True),
        sa.Column("right_normalized_value", sa.Text(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("evidence_direction", sa.String(20), nullable=True),
        sa.Column("evidence_weight", sa.Float(), nullable=True),
        sa.Column("is_legacy_evidence", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provenance", sa.String(100), nullable=False, server_default="PIPELINE_CALCULATED"),
        sa.Column("policy_version", sa.String(50), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint(
            "evidence_direction IS NULL OR evidence_direction IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')",
            name="chk_evidence_dir",
        ),
        sa.CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0.0 AND similarity_score <= 100.0)",
            name="chk_evidence_score_range",
        ),
    )

def downgrade() -> None:
    op.drop_table("candidate_pair_evidence")
    op.drop_table("candidate_blocking_paths")
    op.drop_table("candidate_pairs")
    op.drop_table("normalized_features")
    op.drop_table("normalization_policies")
