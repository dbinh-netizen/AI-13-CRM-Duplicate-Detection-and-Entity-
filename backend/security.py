"""Phân quyền đơn giản theo RFP (SEC 01, REV 03).
Việc cần làm (người phụ trách BE): nối vào API, kiểm tra vai trò trước khi duyệt.
"""

ROLES = ("steward", "approver", "admin")


def can_approve(proposer: str, approver: str) -> bool:
    """Không tự duyệt: người duyệt phải khác người đề xuất (REV 03)."""
    return bool(proposer) and bool(approver) and proposer != approver
