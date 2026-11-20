"""Evidence Builder for SongNhat CRM Duplicate Detection & Entity Resolution.

Sub-milestone: P2.3.5 - Evidence Builder & Database Persistence
Module: backend.matching.evidence_builder

Key Responsibilities:
1. Translates granular PairScoringResult outputs from `similarity_scorer.py` into
   auditable, structured evidence records conforming to the `candidate_pair_evidence` schema.
2. Rigorous Evidence Direction Classification:
   - POSITIVE: Attributes that confirm or strongly suggest duplicate identity.
   - NEGATIVE: Explicit conflicting identifiers or divergent core attributes.
   - NEUTRAL: Missing attributes or circumstantial non-identifying data.
   - ZERO TOLERANCE: Missing attributes are strictly NEUTRAL, NEVER negative!
3. Provenance & Reproducibility Tracking:
   - Binds source versions (left_version_id, right_version_id), normalization policy,
     and scoring policy version into the provenance trail.
4. Lossless Conflict Retention:
   - Preserves all negative and conflict evidence (e.g. SAME_NAME_DIFFERENT_TAX_ID)
     even when the overall total candidate pair score is high.
5. Entity Pool Integrity:
   - Segregates ACCOUNT evidence from CONTACT evidence.
   - Evaluates COMPANY_AFFILIATION strictly as relational context (NOT individual identity).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.matching.blocking_engine import EntityPool, SourceRecordInput
from backend.matching.similarity_scorer import (
    AttributeScoreDetail,
    AttributeStatus,
    PairScoringResult,
    SignalDirection,
)

logger = logging.getLogger(__name__)


class EvidenceItemRecord(BaseModel):
    """Structured in-memory representation of an auditable candidate pair evidence row."""

    model_config = ConfigDict(frozen=True)

    candidate_pair_id: str
    rule_name: str
    field_name: str
    left_raw_value: Optional[str] = None
    right_raw_value: Optional[str] = None
    left_normalized_value: Optional[str] = None
    right_normalized_value: Optional[str] = None
    similarity_score: Optional[float] = None
    evidence_direction: str  # POSITIVE, NEGATIVE, NEUTRAL
    evidence_weight: Optional[float] = None
    provenance: str = "PIPELINE_CALCULATED"
    policy_version: Optional[str] = None
    is_legacy_evidence: bool = False
    explanation: Optional[str] = None

    def __lt__(self, other: EvidenceItemRecord) -> bool:
        return (self.rule_name, self.field_name, self.evidence_direction) < (
            other.rule_name,
            other.field_name,
            other.evidence_direction,
        )


class EvidencePackage(BaseModel):
    """Container for all evidence items belonging to a candidate pair."""

    candidate_pair_id: str
    matching_run_id: Optional[str] = None
    entity_pool: str
    left_source_record_id: str
    right_source_record_id: str
    total_score: float
    evidence_items: List[EvidenceItemRecord] = Field(default_factory=list)
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    conflicts_count: int = 0


class EvidenceBuilder:
    """Constructs auditable evidence rows from scoring results without data mutation."""

    def __init__(
        self,
        entity_pool: str = "ACCOUNT",
        normalization_policy_version: str = "1.0",
        scoring_policy_version: str = "1.0-EXPERIMENTAL",
    ):
        """
        Initialize the Evidence Builder.

        :param entity_pool: Target pool (ACCOUNT or CONTACT).
        :param normalization_policy_version: Normalization policy version tag.
        :param scoring_policy_version: Scoring policy version tag.
        """
        self.entity_pool = entity_pool.upper()
        if self.entity_pool not in (EntityPool.ACCOUNT.value, EntityPool.CONTACT.value):
            raise ValueError(f"Unsupported entity pool: {entity_pool}")

        self.normalization_policy_version = normalization_policy_version
        self.scoring_policy_version = scoring_policy_version

    def build_evidence(
        self,
        candidate_pair_id: Union[UUID, str],
        left: SourceRecordInput,
        right: SourceRecordInput,
        scoring_result: PairScoringResult,
        matching_run_id: Optional[Union[UUID, str]] = None,
    ) -> EvidencePackage:
        """
        Transform PairScoringResult into auditable EvidenceItemRecord instances.

        :param candidate_pair_id: Unique candidate pair ID.
        :param left: Left source record input.
        :param right: Right source record input.
        :param scoring_result: Scoring result produced by SimilarityScorer.
        :param matching_run_id: Optional matching run ID.
        :return: EvidencePackage containing sorted, auditable evidence items.
        """
        # 1. Pool Segregation Validation
        l_pool = left.entity_type.upper()
        r_pool = right.entity_type.upper()
        if l_pool != self.entity_pool or r_pool != self.entity_pool:
            raise ValueError(
                f"Strict Pool Segregation Violation: Cannot build evidence for pair with types "
                f"('{l_pool}', '{r_pool}') in a builder configured for '{self.entity_pool}'."
            )

        pair_id_str = str(candidate_pair_id)
        run_id_str = (
            str(matching_run_id)
            if matching_run_id
            else (scoring_result.matching_run_id if scoring_result else None)
        )

        # 2. Build provenance string
        v_left = str(left.version_id) if left.version_id else f"num_{left.version_number}"
        v_right = str(right.version_id) if right.version_id else f"num_{right.version_number}"
        provenance_str = (
            f"PIPELINE_CALCULATED:left_ver={v_left}:right_ver={v_right}:"
            f"norm_ver={self.normalization_policy_version}"
        )

        items: List[EvidenceItemRecord] = []

        # 3. Process Attribute Scores into Evidence Items
        for attr_name, detail in scoring_result.attribute_scores.items():
            rule_name = f"RULE_{attr_name}"
            field_name = attr_name.lower()

            # Determine direction strictly
            if detail.status == AttributeStatus.MISSING:
                direction = "NEUTRAL"
            elif detail.signal_direction == SignalDirection.POSITIVE:
                direction = "POSITIVE"
            elif detail.signal_direction == SignalDirection.NEGATIVE:
                direction = "NEGATIVE"
            else:
                direction = "NEUTRAL"

            # Clean score for DB check constraint (0.0 <= score <= 100.0)
            score_val = (
                detail.similarity_score
                if detail.status != AttributeStatus.MISSING
                else None
            )

            # Special case for CONTACT company affiliation: explicitly note relational nature
            explanation_text = detail.explanation
            if attr_name == "COMPANY_AFFILIATION":
                explanation_text = (
                    f"{detail.explanation} [RELATIONAL_ONLY: Does not assert personal contact identity]"
                )

            ev = EvidenceItemRecord(
                candidate_pair_id=pair_id_str,
                rule_name=rule_name,
                field_name=field_name,
                left_raw_value=detail.left_raw,
                right_raw_value=detail.right_raw,
                left_normalized_value=detail.left_normalized,
                right_normalized_value=detail.right_normalized,
                similarity_score=score_val,
                evidence_direction=direction,
                evidence_weight=detail.weight,
                provenance=provenance_str,
                policy_version=self.scoring_policy_version,
                is_legacy_evidence=False,
                explanation=explanation_text,
            )
            items.append(ev)

        # 4. Generate Explicit Pattern Conflict Evidence Items
        for conflict_code in scoring_result.conflicts_detected:
            conflict_ev = EvidenceItemRecord(
                candidate_pair_id=pair_id_str,
                rule_name="RULE_CONFLICT_DETECTION",
                field_name=conflict_code.lower(),
                left_raw_value=None,
                right_raw_value=None,
                left_normalized_value=None,
                right_normalized_value=None,
                similarity_score=0.0,
                evidence_direction="NEGATIVE",
                evidence_weight=0.0,
                provenance=provenance_str,
                policy_version=self.scoring_policy_version,
                is_legacy_evidence=False,
                explanation=f"Critical pattern conflict detected: {conflict_code}.",
            )
            items.append(conflict_ev)

        # 5. Deterministic sorting by (rule_name, field_name)
        items.sort()

        # Compute summary counts
        pos_cnt = sum(1 for it in items if it.evidence_direction == "POSITIVE")
        neg_cnt = sum(1 for it in items if it.evidence_direction == "NEGATIVE")
        neu_cnt = sum(1 for it in items if it.evidence_direction == "NEUTRAL")
        conf_cnt = len(scoring_result.conflicts_detected)

        return EvidencePackage(
            candidate_pair_id=pair_id_str,
            matching_run_id=run_id_str,
            entity_pool=self.entity_pool,
            left_source_record_id=str(left.source_record_id),
            right_source_record_id=str(right.source_record_id),
            total_score=scoring_result.total_score,
            evidence_items=items,
            positive_count=pos_cnt,
            negative_count=neg_cnt,
            neutral_count=neu_cnt,
            conflicts_count=conf_cnt,
        )
