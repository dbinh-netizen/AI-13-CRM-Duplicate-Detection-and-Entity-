import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Text, Integer, Float, ForeignKey,
    CheckConstraint, UniqueConstraint, ForeignKeyConstraint, JSON
)
from backend.models.base import Base, GUIDType, ISOUtcDateTime

class NormalizationPolicy(Base):
    __tablename__ = "normalization_policies"
    __table_args__ = (
        UniqueConstraint("policy_name", "version_number", name="uq_policy_version"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="chk_policy_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    policy_name = Column(String(100), nullable=False)
    version_number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="DRAFT")
    config_payload = Column(JSON, nullable=False)
    effective_from = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

class NormalizedFeature(Base):
    __tablename__ = "normalized_features"
    __table_args__ = (
        UniqueConstraint("source_record_version_id", "policy_id", "feature_name", name="uq_norm_feature_version"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    source_record_version_id = Column(GUIDType, ForeignKey("source_record_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_id = Column(GUIDType, ForeignKey("normalization_policies.id", ondelete="RESTRICT"), nullable=False, index=True)
    feature_name = Column(String(100), nullable=False, index=True)
    raw_value = Column(Text, nullable=True)
    normalized_value = Column(Text, nullable=True)
    tokens_payload = Column(JSON, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class CandidatePair(Base):
    __tablename__ = "candidate_pairs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["left_source_record_id", "entity_type"],
            ["source_records.id", "source_records.entity_type"],
            name="fk_cand_pair_left_pool",
            ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["right_source_record_id", "entity_type"],
            ["source_records.id", "source_records.entity_type"],
            name="fk_cand_pair_right_pool",
            ondelete="RESTRICT"
        ),
        UniqueConstraint("matching_run_id", "left_source_record_id", "right_source_record_id", name="uq_cand_pair_run"),
        UniqueConstraint("legacy_pair_id", name="uq_cand_pair_legacy_id"),
        CheckConstraint("left_source_record_id < right_source_record_id", name="chk_cand_pair_order"),
        CheckConstraint("total_score >= 0.0 AND total_score <= 100.0", name="chk_cand_score_range"),
        CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_cand_pair_pool"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    matching_run_id = Column(GUIDType, ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    left_source_record_id = Column(GUIDType, nullable=False, index=True)
    right_source_record_id = Column(GUIDType, nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    total_score = Column(Float, nullable=False)
    decision_tier = Column(String(50), nullable=False)
    proposed_category = Column(String(50), nullable=False)
    legacy_pair_id = Column(Integer, nullable=True, index=True)
    legacy_reasons_raw = Column(Text, nullable=True)
    is_migrated_legacy = Column(Boolean, nullable=False, default=False)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class CandidateBlockingPath(Base):
    __tablename__ = "candidate_blocking_paths"
    __table_args__ = (
        UniqueConstraint("candidate_pair_id", "blocking_key_name", "blocking_value", name="uq_cand_block_path"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    candidate_pair_id = Column(GUIDType, ForeignKey("candidate_pairs.id", ondelete="CASCADE"), nullable=False, index=True)
    blocking_key_name = Column(String(100), nullable=False, index=True)
    blocking_value = Column(String(255), nullable=False, index=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class CandidatePairEvidence(Base):
    __tablename__ = "candidate_pair_evidence"
    __table_args__ = (
        CheckConstraint(
            "evidence_direction IS NULL OR evidence_direction IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')",
            name="chk_evidence_dir"
        ),
        CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0.0 AND similarity_score <= 100.0)",
            name="chk_evidence_score_range"
        ),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    candidate_pair_id = Column(GUIDType, ForeignKey("candidate_pairs.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False)
    field_name = Column(String(100), nullable=False)
    left_raw_value = Column(Text, nullable=True)
    right_raw_value = Column(Text, nullable=True)
    left_normalized_value = Column(Text, nullable=True)
    right_normalized_value = Column(Text, nullable=True)
    similarity_score = Column(Float, nullable=True)
    evidence_direction = Column(String(20), nullable=True)
    evidence_weight = Column(Float, nullable=True)
    is_legacy_evidence = Column(Boolean, nullable=False, default=False)
    provenance = Column(String(100), nullable=False, default="PIPELINE_CALCULATED")
    policy_version = Column(String(50), nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
