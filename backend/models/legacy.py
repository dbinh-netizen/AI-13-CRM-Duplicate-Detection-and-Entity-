from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from backend.models.base import Base, ISOUtcDateTime

class LegacySourceRecord(Base):
    """Bảng lưu trữ tạm thời dữ liệu nguồn legacy sau khi đổi tên tại Revision 0001 (Read-Only)."""
    __tablename__ = "legacy_source_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(100), nullable=False, index=True)
    source_system = Column(String(50), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False) # COMPANY, BRANCH, CONTACT
    name = Column(String(255), nullable=True)
    tax_code = Column(String(50), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    imported_at = Column(ISOUtcDateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

class LegacyCandidatePair(Base):
    """Bảng lưu trữ tạm thời các cặp ứng viên nghi trùng legacy sau khi đổi tên tại Revision 0001 (Read-Only)."""
    __tablename__ = "legacy_candidate_pairs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    left_source_key = Column(String(100), nullable=False, index=True)
    right_source_key = Column(String(100), nullable=False, index=True)
    entity_pool = Column(String(30), nullable=False) # ACCOUNT or CONTACT
    similarity_score = Column(Float, nullable=True)
    proposed_category = Column(String(50), nullable=True)
    review_state = Column(String(50), nullable=True, default="NEW")
    reasons = Column(Text, nullable=True)

class LegacyAuditLog(Base):
    """Bảng lưu trữ tạm thời nhật ký audit legacy sau khi đổi tên tại Revision 0001 (Read-Only)."""
    __tablename__ = "legacy_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(100), nullable=True)
    actor = Column(String(100), nullable=True)
    role = Column(String(50), nullable=True)
    target_pair = Column(String(150), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
