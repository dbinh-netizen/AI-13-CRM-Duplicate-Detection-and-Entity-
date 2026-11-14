import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Text, Integer, ForeignKey,
    CheckConstraint, UniqueConstraint, JSON
)
from backend.models.base import Base, GUIDType, ISOUtcDateTime

class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('CREATE', 'UPDATE', 'DELETE', 'PROPOSE', 'APPROVE', 'REJECT', 'SPLIT', 'MERGE', 'EXPORT', 'LOGIN')",
            name="chk_audit_action"
        ),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False, index=True)
    actor_id = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_username = Column(String(100), nullable=False)
    target_entity_type = Column(String(50), nullable=False, index=True)
    target_entity_id = Column(String(100), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    details_payload = Column(JSON, nullable=False)
    previous_event_hash = Column(String(64), nullable=True)
    event_hash = Column(String(64), nullable=False, index=True)
    is_migrated_legacy = Column(Boolean, nullable=False, default=False)
    hash_generated_at_migration = Column(Boolean, nullable=False, default=False)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("target_table", "entity_type", name="uq_retention_policy_target"),
        CheckConstraint("retention_days > 0", name="chk_retention_period_positive"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    policy_name = Column(String(100), nullable=False)
    target_table = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=True)
    retention_days = Column(Integer, nullable=False)
    action_on_expiry = Column(String(50), nullable=False, default="SOFT_DELETE")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

class DeletionLedger(Base):
    __tablename__ = "deletion_ledger"
    __table_args__ = (
        UniqueConstraint("target_table", "original_record_id", name="uq_deletion_record_target"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    target_table = Column(String(100), nullable=False)
    original_record_id = Column(String(100), nullable=False, index=True)
    deletion_reason = Column(Text, nullable=False)
    authorized_by = Column(GUIDType, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by = Column(String(100), nullable=False)
    compliance_regulation = Column(String(100), nullable=False, default="GDPR_RTBF")
    tombstone_payload = Column(JSON, nullable=True)
    deleted_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class ExportJob(Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        UniqueConstraint("job_code", name="uq_export_jobs_code"),
        CheckConstraint("status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')", name="chk_export_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    job_code = Column(String(100), unique=True, nullable=False, index=True)
    export_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    filter_criteria = Column(JSON, nullable=True)
    total_items_exported = Column(Integer, nullable=False, default=0)
    file_path = Column(String(255), nullable=True)
    file_checksum = Column(String(64), nullable=True)
    requested_by = Column(GUIDType, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    started_at = Column(ISOUtcDateTime, nullable=True)
    completed_at = Column(ISOUtcDateTime, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class ExportManifestItem(Base):
    __tablename__ = "export_manifest_items"
    __table_args__ = (
        UniqueConstraint("export_job_id", "canonical_membership_id", name="uq_export_job_item"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    export_job_id = Column(GUIDType, ForeignKey("export_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    canonical_membership_id = Column(GUIDType, ForeignKey("canonical_memberships.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_record_id = Column(GUIDType, nullable=False, index=True)
    canonical_entity_id = Column(GUIDType, nullable=False, index=True)
    is_superseded = Column(Boolean, nullable=False, default=False)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
