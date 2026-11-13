"""[PHẦN VIỆC: PHÂN GIẢI THỰC THỂ & DUYỆT 2 CẤP ĐỘC LẬP]"""
def verify_independent_approver(steward: str, approver: str) -> bool:
    if not steward or not approver:
        return False
    return steward.strip().lower() != approver.strip().lower()
