"""Phân quyền và bảo mật theo RFP (SEC 01, REV 03).

Tích hợp với backend.review.security cho Milestone P2.4.
"""

from backend.review.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
    verify_independent_approver,
    UserContext,
    get_current_user,
    require_role,
    require_permission,
)

ROLES = ("DATA_STEWARD", "APPROVER", "ADMINISTRATOR", "AUDITOR")


def can_approve(proposer: str, approver: str) -> bool:
    """Không tự duyệt: người duyệt phải khác người đề xuất (REV 03)."""
    return verify_independent_approver(proposer, approver)
