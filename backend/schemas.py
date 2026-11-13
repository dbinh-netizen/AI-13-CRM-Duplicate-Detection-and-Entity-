from pydantic import BaseModel

class ReviewDecisionRequest(BaseModel):
    left_source_key: str
    right_source_key: str
    decision_category: str
    steward_user: str
    approver_user: str
    reason: str
