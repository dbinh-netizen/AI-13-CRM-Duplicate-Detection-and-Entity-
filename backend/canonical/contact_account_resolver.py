"""Contact to Canonical Account Resolution Engine for Milestone P2.5.

Sub-milestone: P2.5 - STEP 3: CONTACT TO ACCOUNT RESOLUTION
Module: backend.canonical.contact_account_resolver

Key Responsibilities:
1. Resolve each Contact's `company_affiliation` against approved Canonical Accounts.
2. Segregate outcomes into exactly 6 business statuses:
   - MATCHED
   - UNRESOLVED
   - AMBIGUOUS
   - CONFLICT
   - PENDING_REVIEW
   - NO_AFFILIATION
3. For MATCHED entities, construct valid `EntityRelationship` graph edges:
   - `PERSON_WORKS_FOR_COMPANY`
   - `PERSON_CONTACTS_BRANCH`
4. Enforce strict graph integrity:
   - from_canonical_id <> to_canonical_id (no self-relationships)
   - Temporal validity (valid_from <= valid_to or valid_to IS NULL)
   - Composite uniqueness (from, to, type, valid_from)
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.canonical.constants import (
    ContactAccountResolutionStatus,
    MembershipStatus,
    RelationshipTypeEnum,
)
from backend.matching.blocking_engine import (
    clean_phone_number,
    clean_tax_id,
    clean_vietnamese_company_name,
    extract_tax_root,
    remove_vietnamese_accents,
)
from backend.models.canonical import CanonicalEntity, CanonicalMembership, EntityRelationship
from backend.models.intake import SourceRecord, SourceSystem

logger = logging.getLogger(__name__)

GENERIC_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "mail.com",
    "zoho.com",
    "protonmail.com",
}


def extract_domain(email: Optional[str]) -> Optional[str]:
    """Extract and validate non-generic domain from email address."""
    if not email or "@" not in email:
        return None
    domain = email.split("@")[-1].strip().lower()
    if domain in GENERIC_EMAIL_DOMAINS:
        return None
    return domain


def jaccard_similarity(tokens1: Set[str], tokens2: Set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


class ResolutionCandidate(BaseModel):
    canonical_account_id: str
    canonical_account_code: str
    score: float
    matched_features: List[str]
    notes: str


class ContactResolutionResult(BaseModel):
    contact_source_record_id: str
    contact_source_key: str
    canonical_contact_id: Optional[str] = None
    canonical_contact_code: Optional[str] = None
    affiliation_raw: Optional[str] = None
    resolution_status: str  # MATCHED, UNRESOLVED, AMBIGUOUS, CONFLICT, PENDING_REVIEW, NO_AFFILIATION
    canonical_account_id: Optional[str] = None
    canonical_account_code: Optional[str] = None
    relationship_type: Optional[str] = None
    confidence_score: float = 0.0
    evidence_reference: str = ""
    candidate_details: List[ResolutionCandidate] = Field(default_factory=list)


class AccountEntityProfile(BaseModel):
    canonical_id: str
    canonical_code: str
    member_records: List[Dict[str, Any]]
    normalized_names: List[str]
    name_tokens: Set[str]
    tax_codes: Set[str]
    tax_roots: Set[str]
    domains: Set[str]
    phones: Set[str]
    subtypes: Set[str]


class ContactAccountResolver:
    """Resolves contact company affiliations against approved canonical accounts."""

    def _build_account_profiles(self, session: Session) -> List[AccountEntityProfile]:
        """Aggregate all active Canonical Accounts and their member SourceRecords."""
        accounts = session.execute(
            select(CanonicalEntity).where(
                and_(
                    CanonicalEntity.entity_type == "ACCOUNT",
                    CanonicalEntity.status == "ACTIVE",
                )
            )
        ).scalars().all()

        profiles: List[AccountEntityProfile] = []

        for acc in accounts:
            memberships = session.execute(
                select(CanonicalMembership).where(
                    and_(
                        CanonicalMembership.canonical_entity_id == acc.id,
                        CanonicalMembership.status == MembershipStatus.USABLE.value,
                        CanonicalMembership.valid_to.is_(None),
                    )
                )
            ).scalars().all()

            source_record_ids = [m.source_record_id for m in memberships]
            if not source_record_ids:
                continue

            records = session.execute(
                select(SourceRecord).where(SourceRecord.id.in_(source_record_ids))
            ).scalars().all()

            norm_names: List[str] = []
            all_name_tokens: Set[str] = set()
            tax_codes: Set[str] = set()
            tax_roots: Set[str] = set()
            domains: Set[str] = set()
            phones: Set[str] = set()
            subtypes: Set[str] = set()
            member_dicts: List[Dict[str, Any]] = []

            for r in records:
                p = r.record_payload or {}
                member_dicts.append(p)
                raw_name = p.get("legal_name") or p.get("company_name") or p.get("primary_name") or ""
                clean_name = clean_vietnamese_company_name(raw_name)
                if clean_name:
                    norm_names.append(clean_name)
                    all_name_tokens.update(clean_name.split())

                tax = clean_tax_id(p.get("tax_code") or p.get("tax_id") or "")
                if tax:
                    tax_codes.add(tax)
                    tax_roots.add(extract_tax_root(tax))

                d = extract_domain(p.get("email"))
                if d:
                    domains.add(d)

                ph = clean_phone_number(p.get("phone") or "")
                if ph:
                    phones.add(ph)

                st = p.get("entity_subtype") or p.get("entity_type") or "COMPANY"
                subtypes.add(st.upper())

            profiles.append(
                AccountEntityProfile(
                    canonical_id=str(acc.id),
                    canonical_code=acc.canonical_code,
                    member_records=member_dicts,
                    normalized_names=norm_names,
                    name_tokens=all_name_tokens,
                    tax_codes=tax_codes,
                    tax_roots=tax_roots,
                    domains=domains,
                    phones=phones,
                    subtypes=subtypes,
                )
            )

        return profiles

    def resolve_contacts(
        self,
        session: Session,
        actor_username: str = "system_contact_resolver",
    ) -> List[ContactResolutionResult]:
        """Resolve all active Contact records against Canonical Accounts."""
        account_profiles = self._build_account_profiles(session)

        # Fetch active Contacts
        contacts = session.execute(
            select(SourceRecord).where(
                and_(
                    SourceRecord.entity_type == "CONTACT",
                    SourceRecord.status == "ACTIVE",
                )
            )
        ).scalars().all()

        results: List[ContactResolutionResult] = []
        now_dt = datetime.now(timezone.utc)

        for contact in contacts:
            payload = contact.record_payload or {}
            # Check canonical contact membership
            mem = session.execute(
                select(CanonicalMembership).where(
                    and_(
                        CanonicalMembership.source_record_id == contact.id,
                        CanonicalMembership.entity_type == "CONTACT",
                        CanonicalMembership.status == MembershipStatus.USABLE.value,
                        CanonicalMembership.valid_to.is_(None),
                    )
                )
            ).scalar_one_or_none()

            canon_contact_id = str(mem.canonical_entity_id) if mem else None
            canon_contact_code = None
            if canon_contact_id:
                ce = session.execute(
                    select(CanonicalEntity).where(CanonicalEntity.id == UUID(canon_contact_id))
                ).scalar_one_or_none()
                canon_contact_code = ce.canonical_code if ce else None

            company_affiliation_raw = (
                payload.get("company_name")
                or payload.get("company_affiliation")
                or payload.get("organization")
                or payload.get("company")
                or ""
            ).strip()

            email_domain = extract_domain(payload.get("email"))
            phone_clean = clean_phone_number(payload.get("phone") or "")
            tax_raw = clean_tax_id(payload.get("tax_code") or "")

            # 1. Check NO_AFFILIATION
            if not company_affiliation_raw and not email_domain and not tax_raw:
                results.append(
                    ContactResolutionResult(
                        contact_source_record_id=str(contact.id),
                        contact_source_key=contact.source_key,
                        canonical_contact_id=canon_contact_id,
                        canonical_contact_code=canon_contact_code,
                        affiliation_raw=None,
                        resolution_status=ContactAccountResolutionStatus.NO_AFFILIATION.value,
                        evidence_reference="No affiliation company name or corporate domain present in record.",
                    )
                )
                continue

            # Contact normalized affiliation
            norm_affil = clean_vietnamese_company_name(company_affiliation_raw)
            affil_tokens = set(norm_affil.split()) if norm_affil else set()

            candidate_matches: List[ResolutionCandidate] = []

            for acc in account_profiles:
                score = 0.0
                matched_features = []

                # Tax code match (if contact has one)
                if tax_raw:
                    if tax_raw in acc.tax_codes:
                        score += 0.95
                        matched_features.append(f"EXACT_TAX_MATCH({tax_raw})")
                    elif extract_tax_root(tax_raw) in acc.tax_roots:
                        score += 0.85
                        matched_features.append(f"TAX_ROOT_MATCH({extract_tax_root(tax_raw)})")

                # Name / Brand matching
                if norm_affil:
                    for acc_norm in acc.normalized_names:
                        if norm_affil == acc_norm:
                            score += 0.85
                            matched_features.append(f"EXACT_NAME_MATCH({norm_affil})")
                            break
                        elif norm_affil in acc_norm or acc_norm in norm_affil:
                            score += 0.70
                            matched_features.append(f"NAME_SUBSTRING_MATCH({norm_affil}~{acc_norm})")
                            break

                    jaccard = jaccard_similarity(affil_tokens, acc.name_tokens)
                    if jaccard >= 0.5 and not any("EXACT_NAME" in f or "SUBSTRING" in f for f in matched_features):
                        score += min(0.65, jaccard * 0.8)
                        matched_features.append(f"NAME_TOKEN_OVERLAP(jaccard={jaccard:.2f})")

                # Email domain match
                if email_domain and email_domain in acc.domains:
                    score += 0.65
                    matched_features.append(f"CORPORATE_DOMAIN_MATCH({email_domain})")

                # Phone match
                if phone_clean and phone_clean in acc.phones:
                    score += 0.40
                    matched_features.append(f"PHONE_MATCH({phone_clean})")

                if score > 0.0:
                    bounded_score = min(1.0, score)
                    candidate_matches.append(
                        ResolutionCandidate(
                            canonical_account_id=acc.canonical_id,
                            canonical_account_code=acc.canonical_code,
                            score=round(bounded_score, 3),
                            matched_features=matched_features,
                            notes=", ".join(matched_features),
                        )
                    )

            # Sort candidate matches descending by score
            candidate_matches.sort(key=lambda x: x.score, reverse=True)

            # Decision Logic
            if not candidate_matches or candidate_matches[0].score < 0.35:
                results.append(
                    ContactResolutionResult(
                        contact_source_record_id=str(contact.id),
                        contact_source_key=contact.source_key,
                        canonical_contact_id=canon_contact_id,
                        canonical_contact_code=canon_contact_code,
                        affiliation_raw=company_affiliation_raw,
                        resolution_status=ContactAccountResolutionStatus.UNRESOLVED.value,
                        confidence_score=candidate_matches[0].score if candidate_matches else 0.0,
                        evidence_reference="No eligible candidate matched with sufficient confidence threshold (>= 0.35).",
                        candidate_details=candidate_matches,
                    )
                )
            elif len(candidate_matches) >= 2 and (candidate_matches[0].score - candidate_matches[1].score < 0.15) and candidate_matches[1].score >= 0.5:
                # Ambiguous: 2 top candidates too close in score
                results.append(
                    ContactResolutionResult(
                        contact_source_record_id=str(contact.id),
                        contact_source_key=contact.source_key,
                        canonical_contact_id=canon_contact_id,
                        canonical_contact_code=canon_contact_code,
                        affiliation_raw=company_affiliation_raw,
                        resolution_status=ContactAccountResolutionStatus.AMBIGUOUS.value,
                        confidence_score=candidate_matches[0].score,
                        evidence_reference=f"Multiple ambiguous account candidates found: {candidate_matches[0].canonical_account_code} ({candidate_matches[0].score}) vs {candidate_matches[1].canonical_account_code} ({candidate_matches[1].score}).",
                        candidate_details=candidate_matches[:3],
                    )
                )
            elif candidate_matches[0].score >= 0.65:
                top = candidate_matches[0]
                target_acc = next(a for a in account_profiles if a.canonical_id == top.canonical_account_id)
                rel_type = (
                    RelationshipTypeEnum.PERSON_CONTACTS_BRANCH.value
                    if "BRANCH" in target_acc.subtypes
                    else RelationshipTypeEnum.PERSON_WORKS_FOR_COMPANY.value
                )

                # Persist EntityRelationship if canonical_contact_id is available
                if canon_contact_id and canon_contact_id != top.canonical_account_id:
                    self._persist_relationship(
                        session=session,
                        from_id=UUID(canon_contact_id),
                        to_id=UUID(top.canonical_account_id),
                        rel_type=rel_type,
                        now_dt=now_dt,
                    )

                results.append(
                    ContactResolutionResult(
                        contact_source_record_id=str(contact.id),
                        contact_source_key=contact.source_key,
                        canonical_contact_id=canon_contact_id,
                        canonical_contact_code=canon_contact_code,
                        affiliation_raw=company_affiliation_raw,
                        resolution_status=ContactAccountResolutionStatus.MATCHED.value,
                        canonical_account_id=top.canonical_account_id,
                        canonical_account_code=top.canonical_account_code,
                        relationship_type=rel_type,
                        confidence_score=top.score,
                        evidence_reference=top.notes,
                        candidate_details=[top],
                    )
                )
            else:
                # Moderate score between 0.35 and 0.65 -> PENDING_REVIEW
                top = candidate_matches[0]
                results.append(
                    ContactResolutionResult(
                        contact_source_record_id=str(contact.id),
                        contact_source_key=contact.source_key,
                        canonical_contact_id=canon_contact_id,
                        canonical_contact_code=canon_contact_code,
                        affiliation_raw=company_affiliation_raw,
                        resolution_status=ContactAccountResolutionStatus.PENDING_REVIEW.value,
                        canonical_account_id=top.canonical_account_id,
                        canonical_account_code=top.canonical_account_code,
                        confidence_score=top.score,
                        evidence_reference=f"Moderate match requiring review ({top.score:.2f}): {top.notes}",
                        candidate_details=[top],
                    )
                )

        session.flush()
        return results

    def _persist_relationship(
        self,
        session: Session,
        from_id: UUID,
        to_id: UUID,
        rel_type: str,
        now_dt: datetime,
    ) -> None:
        """Insert active EntityRelationship edge if not already present."""
        existing = session.execute(
            select(EntityRelationship).where(
                and_(
                    EntityRelationship.from_canonical_id == from_id,
                    EntityRelationship.to_canonical_id == to_id,
                    EntityRelationship.relationship_type == rel_type,
                    EntityRelationship.status == "ACTIVE",
                    EntityRelationship.valid_to.is_(None),
                )
            )
        ).scalar_one_or_none()

        if not existing:
            rel = EntityRelationship(
                id=uuid.uuid4(),
                from_canonical_id=from_id,
                to_canonical_id=to_id,
                relationship_type=rel_type,
                valid_from=now_dt,
                valid_to=None,
                status="ACTIVE",
                created_at=now_dt,
            )
            session.add(rel)
