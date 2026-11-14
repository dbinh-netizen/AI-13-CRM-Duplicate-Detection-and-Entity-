import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Text, Integer, BigInteger, ForeignKey,
    CheckConstraint, UniqueConstraint, ForeignKeyConstraint, JSON
)
from backend.models.base import Base, GUIDType, ISOUtcDateTime

class SourceSystem(Base):
    __tablename__ = "source_systems"
    __table_args__ = (
        UniqueConstraint("id", "entity_type", name="uq_source_sys_id_pool"),
        CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_source_sys_pool"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    source_code = Column(String(50), unique=True, nullable=False, index=True)
    source_name = Column(String(100), nullable=False)
    system_type = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    config_payload = Column(JSON, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("source_system_id", "file_checksum", name="uq_batch_source_checksum"),
        UniqueConstraint("id", "source_system_id", name="uq_import_batch_id_system"),
        CheckConstraint("status IN ('RECEIVED', 'VALIDATING', 'COMPLETED', 'FAILED', 'QUARANTINED')", name="chk_batch_status"),
        CheckConstraint(
            "(batch_type = 'UNMAPPED_QUARANTINE' AND source_system_id IS NULL) OR "
            "(batch_type <> 'UNMAPPED_QUARANTINE' AND source_system_id IS NOT NULL)",
            name="chk_batch_unmapped_source"
        ),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    batch_code = Column(String(100), unique=True, nullable=False, index=True)
    source_system_id = Column(GUIDType, ForeignKey("source_systems.id", ondelete="RESTRICT"), nullable=True, index=True)
    batch_type = Column(String(50), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_checksum = Column(String(64), nullable=False, index=True)
    file_size_bytes = Column(BigInteger, nullable=False)
    total_rows_received = Column(Integer, nullable=False, default=0)
    total_rows_valid = Column(Integer, nullable=False, default=0)
    total_rows_quarantined = Column(Integer, nullable=False, default=0)
    total_rows_rejected = Column(Integer, nullable=False, default=0)
    status = Column(String(50), nullable=False, default="RECEIVED")
    extraction_at = Column(ISOUtcDateTime, nullable=True)
    imported_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    imported_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_system_id", "entity_type"],
            ["source_systems.id", "source_systems.entity_type"],
            name="fk_source_rec_system_pool",
            ondelete="RESTRICT"
        ),
        UniqueConstraint("source_system_id", "entity_type", "source_key", name="uq_source_entity_key"),
        UniqueConstraint("id", "entity_type", name="uq_source_rec_id_pool"),
        CheckConstraint("entity_type IN ('ACCOUNT', 'CONTACT')", name="chk_source_rec_entity_type"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    source_system_id = Column(GUIDType, nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    source_key = Column(String(100), nullable=False, index=True)
    import_batch_id = Column(GUIDType, ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False, index=True)
    entity_subtype = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="ACTIVE")
    record_payload = Column(JSON, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class SourceRecordVersion(Base):
    __tablename__ = "source_record_versions"
    __table_args__ = (
        UniqueConstraint("source_record_id", "version_number", name="uq_source_rec_version"),
        CheckConstraint("version_number >= 1", name="chk_version_num_positive"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="chk_effective_range"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    source_record_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    import_batch_id = Column(GUIDType, ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False, index=True)
    row_anchor_hash = Column(String(64), nullable=False)
    raw_payload = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)
    effective_from = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    effective_to = Column(ISOUtcDateTime, nullable=True)
    is_current = Column(Boolean, nullable=False, default=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class BatchRowResult(Base):
    __tablename__ = "batch_row_results"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "row_number", name="uq_batch_row_num"),
        CheckConstraint("row_status IN ('MIGRATED', 'VALID', 'QUARANTINED', 'REJECTED')", name="chk_row_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    import_batch_id = Column(GUIDType, ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    source_key = Column(String(100), nullable=True)
    row_status = Column(String(50), nullable=False, index=True)
    validation_errors = Column(JSON, nullable=True)
    quarantine_reason = Column(Text, nullable=True)
    raw_row_hash = Column(String(64), nullable=False)
    raw_row_data = Column(JSON, nullable=False)
    source_record_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class SourceIdentifier(Base):
    __tablename__ = "source_identifiers"
    __table_args__ = (
        UniqueConstraint("source_record_id", "identifier_type", "identifier_value", name="uq_source_ident_exact"),
        CheckConstraint(
            "identifier_type IN ('TAX_ID', 'PHONE', 'EMAIL', 'PASSPORT', 'NATIONAL_ID', 'WEBSITE', 'OTHER')",
            name="chk_ident_type"
        ),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    source_record_id = Column(GUIDType, ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True)
    identifier_type = Column(String(50), nullable=False, index=True)
    identifier_value = Column(String(100), nullable=False, index=True)
    issuer = Column(String(100), nullable=True)
    jurisdiction = Column(String(50), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    entity_level = Column(String(50), nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class MatchingRun(Base):
    __tablename__ = "matching_runs"
    __table_args__ = (
        CheckConstraint("entity_pool IN ('ACCOUNT', 'CONTACT')", name="chk_match_run_pool"),
        CheckConstraint("status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')", name="chk_match_run_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    run_code = Column(String(100), unique=True, nullable=False, index=True)
    entity_pool = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="PENDING")
    policy_id = Column(GUIDType, nullable=True) # Soft link to normalization_policies
    total_candidates = Column(Integer, nullable=False, default=0)
    ceiling_breached = Column(Boolean, nullable=False, default=False)
    started_at = Column(ISOUtcDateTime, nullable=True)
    completed_at = Column(ISOUtcDateTime, nullable=True)
    executed_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class RunSource(Base):
    __tablename__ = "run_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_batch_id", "source_system_id"],
            ["import_batches.id", "import_batches.source_system_id"],
            name="fk_run_sources_batch_system",
            ondelete="RESTRICT"
        ),
        UniqueConstraint("matching_run_id", "import_batch_id", name="uq_run_source_batch"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    matching_run_id = Column(GUIDType, ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    import_batch_id = Column(GUIDType, nullable=False, index=True)
    source_system_id = Column(GUIDType, nullable=False, index=True)
    snapshot_cutoff = Column(ISOUtcDateTime, nullable=False)
    is_complete = Column(Boolean, nullable=False, default=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
