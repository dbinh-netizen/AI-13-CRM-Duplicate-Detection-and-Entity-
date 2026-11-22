"""Create Access Control & RBAC schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
        sa.Column("updated_at", ISOUtcDateTime, nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'SUSPENDED')", name="chk_user_status"),
    )

    # 2. roles
    op.create_table(
        "roles",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("role_code", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("role_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
    )

    # 3. permissions
    op.create_table(
        "permissions",
        sa.Column("id", GUIDType, primary_key=True),
        sa.Column("permission_code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", ISOUtcDateTime, nullable=False),
    )

    # 4. user_roles
    op.create_table(
        "user_roles",
        sa.Column("user_id", GUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role_id", GUIDType, sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("assigned_at", ISOUtcDateTime, nullable=False),
        sa.Column("assigned_by", GUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_composite"),
    )

    # 5. role_permissions
    op.create_table(
        "role_permissions",
        sa.Column("role_id", GUIDType, sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("permission_id", GUIDType, sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("granted_at", ISOUtcDateTime, nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_composite"),
    )

def downgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
