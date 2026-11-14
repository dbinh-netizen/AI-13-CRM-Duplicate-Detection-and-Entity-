import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Text, ForeignKey, CheckConstraint, UniqueConstraint, PrimaryKeyConstraint
from backend.models.base import Base, GUIDType, ISOUtcDateTime

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'SUSPENDED')", name="chk_user_status"),
    )

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="ACTIVE")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Role(Base):
    __tablename__ = "roles"

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    role_code = Column(String(50), unique=True, nullable=False, index=True)
    role_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class Permission(Base):
    __tablename__ = "permissions"

    id = Column(GUIDType, primary_key=True, default=uuid.uuid4)
    permission_code = Column(String(100), unique=True, nullable=False, index=True)
    module = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_composite"),
    )

    user_id = Column(GUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(GUIDType, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    assigned_by = Column(GUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_composite"),
    )

    role_id = Column(GUIDType, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id = Column(GUIDType, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_at = Column(ISOUtcDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
