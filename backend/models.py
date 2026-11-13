from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from backend.database import Base

class SourceRecord(Base):
    """Bảng lưu trữ nguyên trạng bản ghi gốc từ CSV"""
    __tablename__ = "source_records"
    id = Column(Integer, primary_key=True, index=True)
    source_key = Column(String(100), unique=True, index=True, nullable=False)
    source_system = Column(String(50), nullable=False)
    entity_type = Column(String(30), nullable=False)  # COMPANY, BRANCH, SITE, CONTACT
    name = Column(String(255))
    tax_code = Column(String(50))
    phone = Column(String(50))
    email = Column(String(150))
    address = Column(Text)
    imported_at = Column(DateTime, default=datetime.utcnow)

class CandidatePair(Base):
    """Bảng lưu các cặp nghi ngờ trùng do thuật toán sinh ra"""
    __tablename__ = "candidate_pairs"
    id = Column(Integer, primary_key=True, index=True)
    left_source_key = Column(String(100), index=True)
    right_source_key = Column(String(100), index=True)
    entity_pool = Column(String(30))  # ACCOUNT hoặc CONTACT
    similarity_score = Column(Float)
    proposed_category = Column(String(50))  # SAME_ENTITY, RELATED_BUT_DISTINCT, DISTINCT
    review_state = Column(String(50), default="NEW")
    reasons = Column(Text)

class AuditLog(Base):
    """Bảng lưu lịch sử đề xuất (Steward) và phê duyệt (Approver)"""
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(100))
    actor = Column(String(100))
    role = Column(String(50))
    target_pair = Column(String(150))
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
