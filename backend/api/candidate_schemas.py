
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class CandidateEvidenceResponse(BaseModel):
    id: UUID
    rule_name: str
    field_name: str | None
    similarity_score: float | None
    evidence_direction: str | None
    evidence_weight: float | None
    provenance: Any = None
    policy_version: str | None


class CandidateReviewTaskResponse(BaseModel):
    task_id: UUID
    task_code: str
    status: str
    priority: str | None


class CandidatePairResponse(BaseModel):
    id: UUID
    matching_run_id: UUID

    left_source_record_id: UUID
    right_source_record_id: UUID

    left_source_key: str
    right_source_key: str

    entity_pool: str
    similarity_score: float | None
    decision_tier: str | None
    proposed_category: str | None

    evidence: list[CandidateEvidenceResponse]
    conflicts: list[CandidateEvidenceResponse]

    review_state: str | None
    review_tasks: list[CandidateReviewTaskResponse]

    created_at: datetime


class CandidateListResponse(BaseModel):
    data_source: str
    total_candidates: int
    limit: int
    offset: int
    candidates: list[CandidatePairResponse]
