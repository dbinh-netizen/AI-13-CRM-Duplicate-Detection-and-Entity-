"""Similarity Scoring Engine for SongNhat CRM Duplicate Detection & Entity Resolution.

Sub-milestone: P2.3.4 - Similarity Scoring Engine
Module: backend.matching.similarity_scorer

Key Capabilities:
1. Attribute-level deterministic similarity calculation across:
   - ACCOUNT: TAX_ID, PHONE, EMAIL, COMPANY_NAME, ADDRESS
   - CONTACT: CONTACT_NAME, PHONE, EMAIL, COMPANY_AFFILIATION
2. Strict Attribute Status Differentiation:
   - MATCH, PARTIAL_MATCH, MISMATCH, MISSING, NOT_APPLICABLE
   - Missing attributes NEVER convert to negative conflict and NEVER accidentally inflate score.
3. Multi-Signal Conflict Detection:
   - Conflicting Tax IDs (Critical Conflict)
   - Same Name but Different Tax ID
   - Same Address but Different Entity
   - Same Brand Name but Different Legal Entities
   - Same Company Affiliation but Different Contacts
4. Policy-Driven Scoring Architecture:
   - Separate policies for ACCOUNT and CONTACT.
   - Explicit version tracking: Normalization Policy & Scoring Policy.
   - Transparently marked as EXPERIMENTAL (not yet approved by Data Owner).
5. Mathematical Safety & Reproducibility:
   - Strict bounded scores [0.0, 100.0], zero NaN/Infinity tolerance.
   - Symmetric evaluation: score(A, B) == score(B, A).
   - Traceable attribute-level explainability for Evidence Builder (P2.3.5).
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from backend.matching.blocking_engine import (
    EntityPool,
    IdentifierItem,
    SourceRecordInput,
    clean_address_tokens,
    clean_email_address,
    clean_phone_number,
    clean_tax_id,
    clean_vietnamese_company_name,
    extract_tax_root,
)


class AttributeStatus(str, Enum):
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SignalDirection(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class SimilarityTier(str, Enum):
    HIGH_SIMILARITY = "HIGH_SIMILARITY"
    MEDIUM_SIMILARITY = "MEDIUM_SIMILARITY"
    LOW_SIMILARITY = "LOW_SIMILARITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AttributeScoreDetail(BaseModel):
    """Granular attribute-level scoring and explainability result."""

    attribute_name: str
    status: AttributeStatus
    similarity_score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0)
    weighted_score: float = Field(ge=0.0)
    signal_direction: SignalDirection
    left_raw: Optional[str] = None
    right_raw: Optional[str] = None
    left_normalized: Optional[str] = None
    right_normalized: Optional[str] = None
    explanation: str
    conflict_flag: bool = False


class ScoringPolicy(BaseModel):
    """Configurable scoring policy governance container."""

    policy_name: str = "DEFAULT_SIMILARITY_POLICY"
    version: str = "1.0-EXPERIMENTAL"
    entity_pool: str = "ACCOUNT"
    weights: Dict[str, float] = Field(default_factory=dict)
    thresholds: Dict[str, float] = Field(default_factory=dict)
    description: str = (
        "Experimental scoring weights and thresholds. "
        "PENDING formal approval from Data Owner / Business Architect."
    )
    is_approved_by_data_owner: bool = False


# Default experimental policies with justified initial weights
DEFAULT_ACCOUNT_SCORING_POLICY = ScoringPolicy(
    policy_name="ACCOUNT_SIMILARITY_POLICY",
    version="1.0-EXPERIMENTAL",
    entity_pool="ACCOUNT",
    weights={
        "TAX_ID": 0.35,        # Definitive legal anchor in Vietnam
        "COMPANY_NAME": 0.30,  # Primary brand & legal identity
        "PHONE": 0.15,         # Direct contact anchor
        "EMAIL": 0.10,         # Corporate domain / mailbox anchor
        "ADDRESS": 0.10,       # Operational location anchor
    },
    thresholds={
        "HIGH_SIMILARITY": 85.0,
        "MEDIUM_SIMILARITY": 60.0,
        "LOW_SIMILARITY": 30.0,
    },
    is_approved_by_data_owner=False,
)

DEFAULT_CONTACT_SCORING_POLICY = ScoringPolicy(
    policy_name="CONTACT_SIMILARITY_POLICY",
    version="1.0-EXPERIMENTAL",
    entity_pool="CONTACT",
    weights={
        "CONTACT_NAME": 0.40,        # Individual identity
        "PHONE": 0.25,               # Personal / mobile anchor
        "EMAIL": 0.25,               # Personal / corporate email anchor
        "COMPANY_AFFILIATION": 0.10, # Relational context only (NOT proof of identity)
    },
    thresholds={
        "HIGH_SIMILARITY": 85.0,
        "MEDIUM_SIMILARITY": 60.0,
        "LOW_SIMILARITY": 30.0,
    },
    is_approved_by_data_owner=False,
)


class PairScoringResult(BaseModel):
    """Complete explainable similarity evaluation result for a candidate pair."""

    matching_run_id: Optional[str] = None
    candidate_pair_id: Optional[str] = None
    left_source_record_id: str
    right_source_record_id: str
    entity_pool: str
    total_score: float = Field(ge=0.0, le=100.0)
    similarity_tier: SimilarityTier
    attribute_scores: Dict[str, AttributeScoreDetail] = Field(default_factory=dict)
    positive_signals: List[str] = Field(default_factory=list)
    negative_signals: List[str] = Field(default_factory=list)
    missing_attributes: List[str] = Field(default_factory=list)
    conflicts_detected: List[str] = Field(default_factory=list)
    normalization_policy_version: str = "1.0"
    scoring_policy_version: str = "1.0-EXPERIMENTAL"
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SimilarityScorer:
    """Core Similarity Scoring Engine."""

    def __init__(
        self,
        entity_pool: str = "ACCOUNT",
        scoring_policy: Optional[ScoringPolicy] = None,
        normalization_policy_version: str = "1.0",
    ):
        """
        Initialize the Similarity Scorer.

        :param entity_pool: ACCOUNT or CONTACT.
        :param scoring_policy: Scoring policy or defaults to experimental policy.
        :param normalization_policy_version: Version string of applied normalization policy.
        """
        self.entity_pool = entity_pool.upper()
        if self.entity_pool not in (EntityPool.ACCOUNT.value, EntityPool.CONTACT.value):
            raise ValueError(f"Unsupported entity pool: {entity_pool}")

        if scoring_policy:
            if scoring_policy.entity_pool.upper() != self.entity_pool:
                raise ValueError(
                    f"Policy pool mismatch: Policy is for '{scoring_policy.entity_pool}', "
                    f"but scorer is initialized for '{self.entity_pool}'."
                )
            self.policy = scoring_policy
        else:
            self.policy = (
                DEFAULT_ACCOUNT_SCORING_POLICY
                if self.entity_pool == EntityPool.ACCOUNT.value
                else DEFAULT_CONTACT_SCORING_POLICY
            )

        self.normalization_policy_version = normalization_policy_version

    # -----------------------------------------------------------------------
    # Attribute Scoring Sub-Methods
    # -----------------------------------------------------------------------

    def score_tax_id(
        self, left: SourceRecordInput, right: SourceRecordInput, weight: float
    ) -> AttributeScoreDetail:
        """Score TAX_ID attribute for ACCOUNT pool."""
        # 1. Collect tax codes and jurisdiction
        left_tax = left.tax_code or left.tax_code_root
        right_tax = right.tax_code or right.tax_code_root

        left_jur = "VN"
        right_jur = "VN"

        for ident in left.identifiers:
            if ident.identifier_type.upper() == "TAX_ID" and ident.identifier_value:
                if not left_tax:
                    left_tax = ident.identifier_value
                if ident.jurisdiction:
                    left_jur = ident.jurisdiction.upper()
                break

        for ident in right.identifiers:
            if ident.identifier_type.upper() == "TAX_ID" and ident.identifier_value:
                if not right_tax:
                    right_tax = ident.identifier_value
                if ident.jurisdiction:
                    right_jur = ident.jurisdiction.upper()
                break

        # Check missing
        if not left_tax or not right_tax:
            return AttributeScoreDetail(
                attribute_name="TAX_ID",
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=left_tax,
                right_raw=right_tax,
                explanation="Tax ID is missing on one or both records. No negative inference drawn.",
            )

        c_left = clean_tax_id(left_tax)
        c_right = clean_tax_id(right_tax)
        if not c_left or not c_right:
            return AttributeScoreDetail(
                attribute_name="TAX_ID",
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=left_tax,
                right_raw=right_tax,
                explanation="Tax ID is invalid or contains no alphanumeric characters.",
            )

        root_left = extract_tax_root(c_left)
        root_right = extract_tax_root(c_right)

        # Jurisdiction conflict
        if left_jur != right_jur:
            return AttributeScoreDetail(
                attribute_name="TAX_ID",
                status=AttributeStatus.MISMATCH,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEGATIVE,
                left_raw=f"{left_jur}:{left_tax}",
                right_raw=f"{right_jur}:{right_tax}",
                left_normalized=f"{left_jur}:{root_left}",
                right_normalized=f"{right_jur}:{root_right}",
                explanation=f"Jurisdiction conflict: {left_jur} vs {right_jur}.",
                conflict_flag=True,
            )

        if root_left == root_right and root_left:
            # Match
            is_branch = (c_left != c_right)
            exp = (
                "Exact 10-digit tax root match (Branch/Headquarter relationship)."
                if is_branch
                else "Exact Tax ID match."
            )
            return AttributeScoreDetail(
                attribute_name="TAX_ID",
                status=AttributeStatus.MATCH,
                similarity_score=100.0,
                weight=weight,
                weighted_score=round(100.0 * weight, 4),
                signal_direction=SignalDirection.POSITIVE,
                left_raw=left_tax,
                right_raw=right_tax,
                left_normalized=root_left,
                right_normalized=root_right,
                explanation=exp,
                conflict_flag=False,
            )
        else:
            # Critical Tax ID Conflict
            return AttributeScoreDetail(
                attribute_name="TAX_ID",
                status=AttributeStatus.MISMATCH,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEGATIVE,
                left_raw=left_tax,
                right_raw=right_tax,
                left_normalized=root_left,
                right_normalized=root_right,
                explanation=f"Conflicting Tax ID roots: {root_left} vs {root_right}.",
                conflict_flag=True,
            )

    def score_phone(
        self, left: SourceRecordInput, right: SourceRecordInput, weight: float
    ) -> AttributeScoreDetail:
        """Score PHONE attribute supporting multi-phone sets."""
        left_phones = set()
        if left.phone_clean:
            cp = clean_phone_number(left.phone_clean)
            if len(cp) >= 7:
                left_phones.add(cp)
        for p in left.phones_clean:
            cp = clean_phone_number(p)
            if len(cp) >= 7:
                left_phones.add(cp)
        for ident in left.identifiers:
            if ident.identifier_type.upper() in ("PHONE", "TEL", "MOBILE", "HOTLINE"):
                cp = clean_phone_number(ident.identifier_value)
                if len(cp) >= 7:
                    left_phones.add(cp)

        right_phones = set()
        if right.phone_clean:
            cp = clean_phone_number(right.phone_clean)
            if len(cp) >= 7:
                right_phones.add(cp)
        for p in right.phones_clean:
            cp = clean_phone_number(p)
            if len(cp) >= 7:
                right_phones.add(cp)
        for ident in right.identifiers:
            if ident.identifier_type.upper() in ("PHONE", "TEL", "MOBILE", "HOTLINE"):
                cp = clean_phone_number(ident.identifier_value)
                if len(cp) >= 7:
                    right_phones.add(cp)

        if not left_phones or not right_phones:
            return AttributeScoreDetail(
                attribute_name="PHONE",
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=",".join(sorted(left_phones)) or None,
                right_raw=",".join(sorted(right_phones)) or None,
                explanation="Phone number is missing on one or both records.",
            )

        common_phones = left_phones.intersection(right_phones)
        if common_phones:
            matched_phone = sorted(common_phones)[0]
            return AttributeScoreDetail(
                attribute_name="PHONE",
                status=AttributeStatus.MATCH,
                similarity_score=100.0,
                weight=weight,
                weighted_score=round(100.0 * weight, 4),
                signal_direction=SignalDirection.POSITIVE,
                left_raw=",".join(sorted(left_phones)),
                right_raw=",".join(sorted(right_phones)),
                left_normalized=",".join(sorted(left_phones)),
                right_normalized=",".join(sorted(right_phones)),
                explanation=f"Exact phone match on: {matched_phone}.",
            )
        else:
            return AttributeScoreDetail(
                attribute_name="PHONE",
                status=AttributeStatus.MISMATCH,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEGATIVE,
                left_raw=",".join(sorted(left_phones)),
                right_raw=",".join(sorted(right_phones)),
                left_normalized=",".join(sorted(left_phones)),
                right_normalized=",".join(sorted(right_phones)),
                explanation="Different phone numbers without common overlap.",
            )

    def score_email(
        self, left: SourceRecordInput, right: SourceRecordInput, weight: float
    ) -> AttributeScoreDetail:
        """Score EMAIL attribute preserving dots and plus suffixes."""
        left_emails = set()
        if left.email_clean:
            ce = clean_email_address(left.email_clean)
            if "@" in ce:
                left_emails.add(ce)
        for em in left.emails_clean:
            ce = clean_email_address(em)
            if "@" in ce:
                left_emails.add(ce)
        for ident in left.identifiers:
            if ident.identifier_type.upper() == "EMAIL":
                ce = clean_email_address(ident.identifier_value)
                if "@" in ce:
                    left_emails.add(ce)

        right_emails = set()
        if right.email_clean:
            ce = clean_email_address(right.email_clean)
            if "@" in ce:
                right_emails.add(ce)
        for em in right.emails_clean:
            ce = clean_email_address(em)
            if "@" in ce:
                right_emails.add(ce)
        for ident in right.identifiers:
            if ident.identifier_type.upper() == "EMAIL":
                ce = clean_email_address(ident.identifier_value)
                if "@" in ce:
                    right_emails.add(ce)

        if not left_emails or not right_emails:
            return AttributeScoreDetail(
                attribute_name="EMAIL",
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=",".join(sorted(left_emails)) or None,
                right_raw=",".join(sorted(right_emails)) or None,
                explanation="Email is missing on one or both records.",
            )

        common_emails = left_emails.intersection(right_emails)
        if common_emails:
            matched_email = sorted(common_emails)[0]
            return AttributeScoreDetail(
                attribute_name="EMAIL",
                status=AttributeStatus.MATCH,
                similarity_score=100.0,
                weight=weight,
                weighted_score=round(100.0 * weight, 4),
                signal_direction=SignalDirection.POSITIVE,
                left_raw=",".join(sorted(left_emails)),
                right_raw=",".join(sorted(right_emails)),
                left_normalized=",".join(sorted(left_emails)),
                right_normalized=",".join(sorted(right_emails)),
                explanation=f"Exact email match on: {matched_email}.",
            )
        else:
            return AttributeScoreDetail(
                attribute_name="EMAIL",
                status=AttributeStatus.MISMATCH,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEGATIVE,
                left_raw=",".join(sorted(left_emails)),
                right_raw=",".join(sorted(right_emails)),
                left_normalized=",".join(sorted(left_emails)),
                right_normalized=",".join(sorted(right_emails)),
                explanation="Different email addresses.",
            )

    def score_name(
        self,
        left: SourceRecordInput,
        right: SourceRecordInput,
        weight: float,
        is_account: bool = True,
    ) -> AttributeScoreDetail:
        """Score COMPANY_NAME (ACCOUNT) or CONTACT_NAME (CONTACT)."""
        attr_name = "COMPANY_NAME" if is_account else "CONTACT_NAME"

        raw_left = left.normalized_name or left.primary_name
        raw_right = right.normalized_name or right.primary_name

        if not raw_left or not raw_right or not raw_left.strip() or not raw_right.strip():
            return AttributeScoreDetail(
                attribute_name=attr_name,
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=raw_left,
                right_raw=raw_right,
                explanation=f"{attr_name} is missing on one or both records.",
            )

        if is_account:
            # Legal entity stripping for corporate brand comparison
            norm_left = clean_vietnamese_company_name(raw_left)
            norm_right = clean_vietnamese_company_name(raw_right)
        else:
            norm_left = clean_address_tokens(raw_left)
            norm_right = clean_address_tokens(raw_right)

        if not norm_left or not norm_right:
            return AttributeScoreDetail(
                attribute_name=attr_name,
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=raw_left,
                right_raw=raw_right,
                explanation="Name normalization yielded empty string.",
            )

        # 1. Exact match
        if norm_left == norm_right:
            score = 100.0
            status = AttributeStatus.MATCH
            direction = SignalDirection.POSITIVE
            exp = f"Exact normalized {attr_name} match."
        else:
            # 2. Fuzzy Jaro-Winkler and Token Set Ratio
            jw_sim = JaroWinkler.similarity(norm_left, norm_right) * 100.0
            token_sim = fuzz.token_set_ratio(norm_left, norm_right)
            score = max(jw_sim, token_sim)
            score = round(max(0.0, min(100.0, score)), 2)

            if score >= 85.0:
                status = AttributeStatus.MATCH
                direction = SignalDirection.POSITIVE
                exp = f"High fuzzy {attr_name} match ({score:.1f}%)."
            elif score >= 60.0:
                status = AttributeStatus.PARTIAL_MATCH
                direction = SignalDirection.POSITIVE
                exp = f"Partial {attr_name} match ({score:.1f}%)."
            else:
                status = AttributeStatus.MISMATCH
                direction = SignalDirection.NEGATIVE
                exp = f"Divergent {attr_name} ({score:.1f}%)."

        return AttributeScoreDetail(
            attribute_name=attr_name,
            status=status,
            similarity_score=score,
            weight=weight,
            weighted_score=round(score * weight, 4),
            signal_direction=direction,
            left_raw=raw_left,
            right_raw=raw_right,
            left_normalized=norm_left,
            right_normalized=norm_right,
            explanation=exp,
        )

    def score_address(
        self, left: SourceRecordInput, right: SourceRecordInput, weight: float
    ) -> AttributeScoreDetail:
        """Score ADDRESS attribute with multi-part province and street tokens."""
        p_left = clean_address_tokens(left.province_city or "")
        p_right = clean_address_tokens(right.province_city or "")

        s_left = clean_address_tokens(left.street_ward or left.address_normalized or "")
        s_right = clean_address_tokens(right.street_ward or right.address_normalized or "")

        # Check missing
        if (not p_left and not s_left) or (not p_right and not s_right):
            return AttributeScoreDetail(
                attribute_name="ADDRESS",
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                explanation="Address is missing on one or both records.",
            )

        # Province conflict
        if p_left and p_right and p_left != p_right:
            return AttributeScoreDetail(
                attribute_name="ADDRESS",
                status=AttributeStatus.MISMATCH,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEGATIVE,
                left_raw=f"{left.province_city}, {left.street_ward}",
                right_raw=f"{right.province_city}, {right.street_ward}",
                left_normalized=f"{p_left}:{s_left}",
                right_normalized=f"{p_right}:{s_right}",
                explanation=f"Conflicting provinces: '{p_left}' vs '{p_right}'.",
            )

        # Only province present (no street)
        if (not s_left or not s_right) and p_left == p_right:
            # Same province alone is only weak circumstantial evidence (not duplicate)
            return AttributeScoreDetail(
                attribute_name="ADDRESS",
                status=AttributeStatus.PARTIAL_MATCH,
                similarity_score=20.0,
                weight=weight,
                weighted_score=round(20.0 * weight, 4),
                signal_direction=SignalDirection.NEUTRAL,
                left_normalized=p_left,
                right_normalized=p_right,
                explanation="Same province but street address missing on one or both records.",
            )

        # Compare street tokens
        if s_left == s_right and s_left:
            score = 100.0
            status = AttributeStatus.MATCH
            direction = SignalDirection.POSITIVE
            exp = "Exact address match."
        else:
            token_ratio = fuzz.token_set_ratio(s_left, s_right)
            score = round(max(0.0, min(100.0, token_ratio)), 2)

            if score >= 85.0:
                status = AttributeStatus.MATCH
                direction = SignalDirection.POSITIVE
                exp = f"High address token match ({score:.1f}%)."
            elif score >= 50.0:
                status = AttributeStatus.PARTIAL_MATCH
                direction = SignalDirection.POSITIVE
                exp = f"Partial address token match ({score:.1f}%)."
            else:
                status = AttributeStatus.MISMATCH
                direction = SignalDirection.NEGATIVE
                exp = f"Divergent address ({score:.1f}%)."

        return AttributeScoreDetail(
            attribute_name="ADDRESS",
            status=status,
            similarity_score=score,
            weight=weight,
            weighted_score=round(score * weight, 4),
            signal_direction=direction,
            left_raw=f"{left.province_city}, {left.street_ward}",
            right_raw=f"{right.province_city}, {right.street_ward}",
            left_normalized=f"{p_left}:{s_left}",
            right_normalized=f"{p_right}:{s_right}",
            explanation=exp,
        )

    def score_company_affiliation(
        self, left: SourceRecordInput, right: SourceRecordInput, weight: float
    ) -> AttributeScoreDetail:
        """Score COMPANY_AFFILIATION for CONTACT pool (relational context only)."""
        aff_left = left.raw_payload.get("company_name") or left.raw_payload.get("account_name")
        aff_right = right.raw_payload.get("company_name") or right.raw_payload.get("account_name")

        if not aff_left or not aff_right:
            return AttributeScoreDetail(
                attribute_name="COMPANY_AFFILIATION",
                status=AttributeStatus.MISSING,
                similarity_score=0.0,
                weight=weight,
                weighted_score=0.0,
                signal_direction=SignalDirection.NEUTRAL,
                explanation="Company affiliation missing on one or both contacts.",
            )

        clean_l = clean_vietnamese_company_name(str(aff_left))
        clean_r = clean_vietnamese_company_name(str(aff_right))

        if clean_l == clean_r and clean_l:
            return AttributeScoreDetail(
                attribute_name="COMPANY_AFFILIATION",
                status=AttributeStatus.MATCH,
                similarity_score=100.0,
                weight=weight,
                weighted_score=round(100.0 * weight, 4),
                signal_direction=SignalDirection.POSITIVE,
                left_raw=str(aff_left),
                right_raw=str(aff_right),
                left_normalized=clean_l,
                right_normalized=clean_r,
                explanation=(
                    "Matched company affiliation. "
                    "NOTE: Relational corporate context only; does NOT prove contacts are the same person."
                ),
            )
        else:
            token_ratio = fuzz.token_set_ratio(clean_l, clean_r)
            score = round(max(0.0, min(100.0, token_ratio)), 2)
            status = AttributeStatus.PARTIAL_MATCH if score >= 70.0 else AttributeStatus.MISMATCH
            return AttributeScoreDetail(
                attribute_name="COMPANY_AFFILIATION",
                status=status,
                similarity_score=score,
                weight=weight,
                weighted_score=round(score * weight, 4),
                signal_direction=SignalDirection.NEUTRAL,
                left_raw=str(aff_left),
                right_raw=str(aff_right),
                explanation="Different company affiliations.",
            )

    # -----------------------------------------------------------------------
    # Main Evaluation Orchestrator
    # -----------------------------------------------------------------------

    def score_candidate_pair(
        self,
        left: SourceRecordInput,
        right: SourceRecordInput,
        matching_run_id: Optional[Union[UUID, str]] = None,
        candidate_pair_id: Optional[Union[UUID, str]] = None,
    ) -> PairScoringResult:
        """
        Evaluate full multi-attribute similarity between two candidate records.

        :param left: Left source record.
        :param right: Right source record.
        :param matching_run_id: Optional matching run ID.
        :param candidate_pair_id: Optional candidate pair ID.
        :return: PairScoringResult containing total score, tier, and attribute breakdown.
        """
        # 1. Pool Segregation Validation
        l_pool = left.entity_type.upper()
        r_pool = right.entity_type.upper()
        if l_pool != self.entity_pool or r_pool != self.entity_pool:
            raise ValueError(
                f"Strict Pool Segregation Violation: Cannot evaluate pair with types "
                f"('{l_pool}', '{r_pool}') in a scorer configured for '{self.entity_pool}'."
            )

        weights = self.policy.weights
        total_weight_configured = sum(weights.values())
        if total_weight_configured <= 0.0 or math.isnan(total_weight_configured):
            raise ValueError(
                f"Invalid scoring policy configuration: Total weight is {total_weight_configured}."
            )

        attribute_scores: Dict[str, AttributeScoreDetail] = {}
        positive_signals: List[str] = []
        negative_signals: List[str] = []
        missing_attributes: List[str] = []
        conflicts_detected: List[str] = []

        is_account = (self.entity_pool == EntityPool.ACCOUNT.value)

        # 2. Evaluate attributes based on entity pool
        if is_account:
            # TAX_ID
            if "TAX_ID" in weights:
                det = self.score_tax_id(left, right, weights["TAX_ID"])
                attribute_scores["TAX_ID"] = det

            # COMPANY_NAME
            if "COMPANY_NAME" in weights:
                det = self.score_name(left, right, weights["COMPANY_NAME"], is_account=True)
                attribute_scores["COMPANY_NAME"] = det

            # PHONE
            if "PHONE" in weights:
                det = self.score_phone(left, right, weights["PHONE"])
                attribute_scores["PHONE"] = det

            # EMAIL
            if "EMAIL" in weights:
                det = self.score_email(left, right, weights["EMAIL"])
                attribute_scores["EMAIL"] = det

            # ADDRESS
            if "ADDRESS" in weights:
                det = self.score_address(left, right, weights["ADDRESS"])
                attribute_scores["ADDRESS"] = det
        else:
            # CONTACT pool
            if "CONTACT_NAME" in weights:
                det = self.score_name(left, right, weights["CONTACT_NAME"], is_account=False)
                attribute_scores["CONTACT_NAME"] = det

            if "PHONE" in weights:
                det = self.score_phone(left, right, weights["PHONE"])
                attribute_scores["PHONE"] = det

            if "EMAIL" in weights:
                det = self.score_email(left, right, weights["EMAIL"])
                attribute_scores["EMAIL"] = det

            if "COMPANY_AFFILIATION" in weights:
                det = self.score_company_affiliation(left, right, weights["COMPANY_AFFILIATION"])
                attribute_scores["COMPANY_AFFILIATION"] = det

        # 3. Categorize signals & compute total score
        numerator = 0.0
        for attr, detail in attribute_scores.items():
            numerator += detail.weighted_score

            if detail.status == AttributeStatus.MISSING:
                missing_attributes.append(attr)
            elif detail.signal_direction == SignalDirection.POSITIVE:
                positive_signals.append(attr)
            elif detail.signal_direction == SignalDirection.NEGATIVE:
                negative_signals.append(attr)

            if detail.conflict_flag:
                conflicts_detected.append(f"CONFLICT_{attr}")

        raw_total_score = numerator / total_weight_configured
        if math.isnan(raw_total_score) or math.isinf(raw_total_score):
            total_score = 0.0
        else:
            total_score = round(max(0.0, min(100.0, raw_total_score)), 2)

        # 4. Multi-Signal Pattern Conflict Checks
        if is_account:
            tax_det = attribute_scores.get("TAX_ID")
            name_det = attribute_scores.get("COMPANY_NAME")
            addr_det = attribute_scores.get("ADDRESS")

            # Conflict: Same Name but Different Tax ID
            if (
                name_det and name_det.similarity_score >= 85.0
                and tax_det and tax_det.status == AttributeStatus.MISMATCH
            ):
                conflicts_detected.append("SAME_NAME_DIFFERENT_TAX_ID")

            # Conflict: Same Address but Different Legal Entity Name
            if (
                addr_det and addr_det.similarity_score >= 85.0
                and name_det and name_det.status == AttributeStatus.MISMATCH
            ):
                conflicts_detected.append("SAME_ADDRESS_DIFFERENT_ENTITY")

            # Brand Match with Legal Form Variance
            if (
                name_det and name_det.status == AttributeStatus.MATCH
                and left.primary_name and right.primary_name
                and left.primary_name.strip() != right.primary_name.strip()
            ):
                conflicts_detected.append("BRAND_MATCH_LEGAL_VARIANCE")
        else:
            # CONTACT pattern checks
            name_det = attribute_scores.get("CONTACT_NAME")
            aff_det = attribute_scores.get("COMPANY_AFFILIATION")
            if (
                aff_det and aff_det.similarity_score >= 90.0
                and name_det and name_det.status == AttributeStatus.MISMATCH
            ):
                conflicts_detected.append("SAME_COMPANY_DIFFERENT_CONTACT")

        # 5. Determine Similarity Tier
        thresholds = self.policy.thresholds
        high_th = thresholds.get("HIGH_SIMILARITY", 85.0)
        med_th = thresholds.get("MEDIUM_SIMILARITY", 60.0)
        low_th = thresholds.get("LOW_SIMILARITY", 30.0)

        # If all or nearly all attributes are missing -> INSUFFICIENT_EVIDENCE
        if len(missing_attributes) == len(attribute_scores):
            tier = SimilarityTier.INSUFFICIENT_EVIDENCE
        elif total_score >= high_th:
            tier = SimilarityTier.HIGH_SIMILARITY
        elif total_score >= med_th:
            tier = SimilarityTier.MEDIUM_SIMILARITY
        elif total_score >= low_th:
            tier = SimilarityTier.LOW_SIMILARITY
        else:
            tier = SimilarityTier.INSUFFICIENT_EVIDENCE

        return PairScoringResult(
            matching_run_id=str(matching_run_id) if matching_run_id else None,
            candidate_pair_id=str(candidate_pair_id) if candidate_pair_id else None,
            left_source_record_id=str(left.source_record_id),
            right_source_record_id=str(right.source_record_id),
            entity_pool=self.entity_pool,
            total_score=total_score,
            similarity_tier=tier,
            attribute_scores=attribute_scores,
            positive_signals=positive_signals,
            negative_signals=negative_signals,
            missing_attributes=missing_attributes,
            conflicts_detected=conflicts_detected,
            normalization_policy_version=self.normalization_policy_version,
            scoring_policy_version=self.policy.version,
        )
