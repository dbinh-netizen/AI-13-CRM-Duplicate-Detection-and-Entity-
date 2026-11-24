from backend.api.candidate_schemas import CandidateListResponse
from collections import defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, aliased

from backend.database import get_db
from backend.models import SourceRecord
from backend.models.matching import (
    CandidatePair,
    CandidatePairEvidence,
)
from backend.models.review import ReviewTask


router = APIRouter(tags=["Candidate Pairs API"])


@router.get(
    "/candidates",
    response_model=CandidateListResponse,
    summary="Get candidate pairs from Database",
    description=(
        "Read persisted matching results, evidence, conflicts "
        "and review task statuses. "
        "No automatic merge or CRM writeback is performed."
    ),
)
def get_duplicate_candidates(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    entity_type: Literal["ACCOUNT", "CONTACT"] | None = None,
    matching_run_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    left_record = aliased(SourceRecord)
    right_record = aliased(SourceRecord)

    query = (
        db.query(
            CandidatePair,
            left_record.source_key,
            right_record.source_key,
        )
        .join(
            left_record,
            CandidatePair.left_source_record_id == left_record.id,
        )
        .join(
            right_record,
            CandidatePair.right_source_record_id == right_record.id,
        )
    )

    if entity_type is not None:
        query = query.filter(
            CandidatePair.entity_type == entity_type
        )

    if matching_run_id is not None:
        query = query.filter(
            CandidatePair.matching_run_id == matching_run_id
        )

    total = query.count()

    rows = (
        query.order_by(
            CandidatePair.total_score.desc(),
            CandidatePair.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    pair_ids = [pair.id for pair, _, _ in rows]

    evidence_by_pair = defaultdict(list)
    tasks_by_pair = defaultdict(list)

    if pair_ids:
        evidence_rows = (
            db.query(CandidatePairEvidence)
            .filter(
                CandidatePairEvidence.candidate_pair_id.in_(pair_ids)
            )
            .order_by(
                CandidatePairEvidence.rule_name,
                CandidatePairEvidence.id,
            )
            .all()
        )

        for item in evidence_rows:
            evidence_by_pair[item.candidate_pair_id].append({
                "id": str(item.id),
                "rule_name": item.rule_name,
                "field_name": item.field_name,
                "similarity_score": item.similarity_score,
                "evidence_direction": item.evidence_direction,
                "evidence_weight": item.evidence_weight,
                "provenance": item.provenance,
                "policy_version": item.policy_version,
            })

        review_tasks = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.candidate_pair_id.in_(pair_ids)
            )
            .order_by(
                ReviewTask.created_at.desc(),
                ReviewTask.id.desc(),
            )
            .all()
        )

        for task in review_tasks:
            tasks_by_pair[task.candidate_pair_id].append({
                "task_id": str(task.id),
                "task_code": task.task_code,
                "status": task.status,
                "priority": task.priority,
            })

    candidates = []

    for pair, left_key, right_key in rows:
        evidence = evidence_by_pair[pair.id]
        review_tasks = tasks_by_pair[pair.id]

        conflicts = [
            item
            for item in evidence
            if item["rule_name"] == "RULE_CONFLICT_DETECTION"
            and item["evidence_direction"] == "NEGATIVE"
        ]

        candidates.append({
            "id": str(pair.id),
            "matching_run_id": str(pair.matching_run_id),
            "left_source_record_id": str(
                pair.left_source_record_id
            ),
            "right_source_record_id": str(
                pair.right_source_record_id
            ),
            "left_source_key": left_key,
            "right_source_key": right_key,
            "entity_pool": pair.entity_type,
            "similarity_score": pair.total_score,
            "decision_tier": pair.decision_tier,
            "proposed_category": pair.proposed_category,
            "evidence": evidence,
            "conflicts": conflicts,
            "review_state": (
                review_tasks[0]["status"]
                if review_tasks else None
            ),
            "review_tasks": review_tasks,
            "created_at": pair.created_at,
        })

    return {
        "data_source": "DATABASE",
        "total_candidates": total,
        "limit": limit,
        "offset": offset,
        "candidates": candidates,
    }
