import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Text, ForeignKey,
    CheckConstraint, UniqueConstraint, ForeignKeyConstraint
)
from backend.models.base import Base, GUIDType, ISOUtcDateTime

class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"
    __table_args__ = (
        UniqueConstraint("canonical_code", name="uq_canonical_code"),
        UniqueConstraint("id", "entity_type", name="uq_canonical_id_pool"),
        CheckConstraint("entity_pool IN ('ACCOUNT', 'CONTACT')" if False else "entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_canonical_pool"),
        CheckConstraint("status IN ('ACTIVE', 'MERGED', 'SPLIT', 'ARCHIVED')", name="chk_canonical_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    canonical_code = Column(String(100), unique=True, nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="ACTIVE")
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

class CanonicalMembership(Base):
    __tablename__ = "canonical_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canonical_entity_id", "entity_type"],
            ["canonical_entities.id", "canonical_entities.entity_type"],
            name="fk_canon_mem_entity",
            ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["source_record_id", "entity_type"],
            ["source_records.id", "source_records.entity_type"],
            name="fk_canon_mem_record",
            ondelete="RESTRICT"
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_temporal_validity"),
        CheckConstraint("status IN ('USABLE', 'HELD', 'SUPERSEDED', 'RETRACTED')", name="chk_membership_status"),
        CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_canon_mem_pool"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    canonical_entity_id = Column(GUIDType, nullable=False, index=True)
    source_record_id = Column(GUIDType, nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    valid_from = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_to = Column(ISOUtcDateTime, nullable=True)
    status = Column(String(50), nullable=False, default="USABLE", index=True)
    review_decision_id = Column(GUIDType, ForeignKey("review_decisions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class CanonicalField(Base):
    __tablename__ = "canonical_fields"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_field_temporal_validity"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    canonical_entity_id = Column(GUIDType, ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False, index=True)
    field_value = Column(Text, nullable=True)
    valid_from = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_to = Column(ISOUtcDateTime, nullable=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class CanonicalFieldProvenance(Base):
    __tablename__ = "canonical_field_provenance"
    __table_args__ = (
        CheckConstraint(
            "provenance_type IN ('DIRECT_SOURCE', 'STEWARD_OVERRIDE', 'AGGREGATED_RULE')",
            name="chk_provenance_type"
        ),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    canonical_field_id = Column(GUIDType, ForeignKey("canonical_fields.id", ondelete="CASCADE"), nullable=False, index=True)
    source_record_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_record_version_id = Column(GUIDType, ForeignKey("source_record_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_field_name = Column(String(100), nullable=False)
    provenance_type = Column(String(50), nullable=False, default="DIRECT_SOURCE")
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class EntityRelationship(Base):
    __tablename__ = "entity_relationships"
    __table_args__ = (
        UniqueConstraint("from_canonical_id", "to_canonical_id", "relationship_type", "valid_from", name="uq_entity_relationship_edge"),
        CheckConstraint("from_canonical_id <> to_canonical_id", name="chk_no_self_relationship"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_rel_temporal_validity"),
        CheckConstraint("status IN ('ACTIVE', 'TERMINATED', 'DISPUTED')", name="chk_rel_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    from_canonical_id = Column(GUIDType, ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    to_canonical_id = Column(GUIDType, ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=False, index=True)
    valid_from = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_to = Column(ISOUtcDateTime, nullable=True)
    status = Column(String(50), nullable=False, default="ACTIVE")
    review_decision_id = Column(GUIDType, ForeignKey("review_decisions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
