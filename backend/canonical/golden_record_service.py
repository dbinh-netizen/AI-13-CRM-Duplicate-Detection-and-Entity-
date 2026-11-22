"""Golden Record Consolidation Engine for Milestone P2.5.

Sub-milestone: P2.5 - STEP 5: GOLDEN RECORD CONSOLIDATION
Module: backend.canonical.golden_record_service

Key Responsibilities:
1. Field-level survivorship strategies:
   - SOURCE_PRIORITY: e.g., CRM_A > CRM_B > CRM_C
   - LATEST_VALID_VALUE: latest timestamped non-empty value
   - VERIFIED_VALUE: standardized format (e.g., valid 10/13-digit tax code)
   - MANUAL_OVERRIDE: human steward input
   - CONFLICT_REVIEW: unresolved competing values
2. Populate `canonical_fields`:
   - canonical_entity_id, field_name, field_value, valid_from, valid_to, is_current
3. Populate `canonical_field_provenance`:
   - canonical_field_id, source_record_id, source_record_version_id, source_field_name, provenance_type
4. Temporal integrity:
   - Updating a canonical field deactivates previous version (is_current=False, valid_to=now).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.canonical.constants import (
    GoldenRecordStrategy,
    MembershipStatus,
    ProvenanceTypeEnum,
)
from backend.models.canonical import (
    CanonicalEntity,
    CanonicalField,
    CanonicalFieldProvenance,
    CanonicalMembership,
)
from backend.models.intake import SourceRecord, SourceRecordVersion, SourceSystem

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_PRIORITY: Dict[str, int] = {
    "CRM_A": 100,
    "ERP_NORTH": 100,
    "CRM_B": 80,
    "CRM_SOUTH": 80,
    "CRM_C": 60,
    "WEB_LEAD": 40,
    "ZALO_LEAD": 30,
}


class FieldConsolidationPolicy(BaseModel):
    field_name: str
    strategy: GoldenRecordStrategy = GoldenRecordStrategy.SOURCE_PRIORITY
    source_priority_weights: Dict[str, int] = Field(default_factory=lambda: DEFAULT_SOURCE_PRIORITY)
    require_verified_format: bool = False


class GoldenRecordSummary(BaseModel):
    canonical_entity_id: str
    canonical_code: str
    fields_consolidated: Dict[str, Any] = Field(default_factory=dict)
    provenance_records_created: int = 0


class GoldenRecordService:
    """Service producing consolidated Golden Records with field-level survivorship and provenance."""

    def __init__(
        self,
        policies: Optional[Dict[str, FieldConsolidationPolicy]] = None,
    ):
        self.policies = policies or self._get_default_policies()

    @staticmethod
    def _get_default_policies() -> Dict[str, FieldConsolidationPolicy]:
        return {
            "legal_name": FieldConsolidationPolicy(
                field_name="legal_name",
                strategy=GoldenRecordStrategy.SOURCE_PRIORITY,
            ),
            "tax_code": FieldConsolidationPolicy(
                field_name="tax_code",
                strategy=GoldenRecordStrategy.VERIFIED_VALUE,
                require_verified_format=True,
            ),
            "phone": FieldConsolidationPolicy(
                field_name="phone",
                strategy=GoldenRecordStrategy.LATEST_VALID_VALUE,
            ),
            "email": FieldConsolidationPolicy(
                field_name="email",
                strategy=GoldenRecordStrategy.LATEST_VALID_VALUE,
            ),
            "address": FieldConsolidationPolicy(
                field_name="address",
                strategy=GoldenRecordStrategy.SOURCE_PRIORITY,
            ),
            "contact_name": FieldConsolidationPolicy(
                field_name="contact_name",
                strategy=GoldenRecordStrategy.SOURCE_PRIORITY,
            ),
        }

    def consolidate_entity(
        self,
        session: Session,
        canonical_entity_id: Union[UUID, str],
        now_dt: Optional[datetime] = None,
    ) -> GoldenRecordSummary:
        """Consolidate fields for a single CanonicalEntity."""
        now_dt = now_dt or datetime.now(timezone.utc)
        c_uuid = UUID(str(canonical_entity_id))

        canon_entity = session.execute(
            select(CanonicalEntity).where(CanonicalEntity.id == c_uuid)
        ).scalar_one_or_none()
        if not canon_entity:
            raise ValueError(f"CanonicalEntity '{canonical_entity_id}' not found.")

        # Fetch active members
        memberships = session.execute(
            select(CanonicalMembership).where(
                and_(
                    CanonicalMembership.canonical_entity_id == c_uuid,
                    CanonicalMembership.status == MembershipStatus.USABLE.value,
                    CanonicalMembership.valid_to.is_(None),
                )
            )
        ).scalars().all()

        if not memberships:
            return GoldenRecordSummary(
                canonical_entity_id=str(c_uuid),
                canonical_code=canon_entity.canonical_code,
            )

        # Fetch member records and their latest versions
        source_rec_ids = [m.source_record_id for m in memberships]
        source_records = session.execute(
            select(SourceRecord).where(SourceRecord.id.in_(source_rec_ids))
        ).scalars().all()

        rec_map = {r.id: r for r in source_records}

        # Fetch source systems
        sys_ids = list({r.source_system_id for r in source_records})
        systems = session.execute(
            select(SourceSystem).where(SourceSystem.id.in_(sys_ids))
        ).scalars().all()
        sys_code_map = {s.id: s.source_code for s in systems}

        # Fetch latest versions
        versions = session.execute(
            select(SourceRecordVersion)
            .where(SourceRecordVersion.source_record_id.in_(source_rec_ids))
            .order_by(SourceRecordVersion.version_number.desc())
        ).scalars().all()
        latest_ver_map: Dict[UUID, SourceRecordVersion] = {}
        for v in versions:
            if v.source_record_id not in latest_ver_map:
                latest_ver_map[v.source_record_id] = v

        # Determine target fields based on entity pool
        if canon_entity.entity_type == "ACCOUNT":
            target_fields = ["legal_name", "tax_code", "phone", "email", "address"]
        else:
            target_fields = ["contact_name", "phone", "email"]

        consolidated_result: Dict[str, Any] = {}
        provenance_count = 0

        for field_name in target_fields:
            policy = self.policies.get(
                field_name,
                FieldConsolidationPolicy(field_name=field_name),
            )

            # Candidate values across member records
            candidate_values: List[Dict[str, Any]] = []

            for m in memberships:
                r = rec_map.get(m.source_record_id)
                if not r:
                    continue

                p = r.record_payload or {}
                # Field alias lookup
                raw_val = None
                if field_name == "legal_name":
                    raw_val = p.get("legal_name") or p.get("company_name") or p.get("primary_name")
                elif field_name == "contact_name":
                    raw_val = p.get("contact_name") or p.get("full_name") or p.get("name")
                else:
                    raw_val = p.get(field_name)

                if raw_val is not None and str(raw_val).strip() != "":
                    sys_code = sys_code_map.get(r.source_system_id, "CRM_A")
                    candidate_values.append({
                        "value": str(raw_val).strip(),
                        "source_record_id": r.id,
                        "source_system_code": sys_code,
                        "priority_weight": policy.source_priority_weights.get(sys_code, 10),
                        "updated_at": r.updated_at or r.created_at,
                        "version": latest_ver_map.get(r.id),
                    })

            if not candidate_values:
                continue

            # Apply survivorship rule
            chosen = self._select_winning_value(candidate_values, policy)
            if not chosen:
                continue

            winning_val = chosen["value"]
            winning_rec_id = chosen["source_record_id"]
            winning_ver = chosen["version"]

            # Save to canonical_fields
            # Supersede old current field
            existing_field = session.execute(
                select(CanonicalField).where(
                    and_(
                        CanonicalField.canonical_entity_id == c_uuid,
                        CanonicalField.field_name == field_name,
                        CanonicalField.is_current == True,
                    )
                )
            ).scalar_one_or_none()

            if existing_field:
                if existing_field.field_value == winning_val:
                    consolidated_result[field_name] = winning_val
                    continue
                existing_field.is_current = False
                existing_field.valid_to = now_dt

            field_id = uuid.uuid4()
            cf = CanonicalField(
                id=field_id,
                canonical_entity_id=c_uuid,
                field_name=field_name,
                field_value=winning_val,
                valid_from=now_dt,
                valid_to=None,
                is_current=True,
                created_at=now_dt,
            )
            session.add(cf)
            session.flush()

            # Save to canonical_field_provenance
            if winning_ver:
                prov = CanonicalFieldProvenance(
                    id=uuid.uuid4(),
                    canonical_field_id=field_id,
                    source_record_id=winning_rec_id,
                    source_record_version_id=winning_ver.id,
                    source_field_name=field_name,
                    provenance_type=ProvenanceTypeEnum.DIRECT_SOURCE.value,
                    created_at=now_dt,
                )
                session.add(prov)
                provenance_count += 1

            consolidated_result[field_name] = winning_val

        session.flush()
        return GoldenRecordSummary(
            canonical_entity_id=str(c_uuid),
            canonical_code=canon_entity.canonical_code,
            fields_consolidated=consolidated_result,
            provenance_records_created=provenance_count,
        )

    def _select_winning_value(
        self,
        candidates: List[Dict[str, Any]],
        policy: FieldConsolidationPolicy,
    ) -> Optional[Dict[str, Any]]:
        """Choose winning candidate value based on strategy."""
        if not candidates:
            return None

        if policy.strategy == GoldenRecordStrategy.VERIFIED_VALUE:
            # Prefer 10-digit clean tax code or strictly validated format
            for c in candidates:
                val = str(c["value"]).strip()
                if val.isdigit() and len(val) in (10, 13):
                    return c
            # Fallback to source priority
            candidates.sort(key=lambda x: x["priority_weight"], reverse=True)
            return candidates[0]

        elif policy.strategy == GoldenRecordStrategy.LATEST_VALID_VALUE:
            # Sort by updated_at descending
            candidates.sort(key=lambda x: x["updated_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return candidates[0]

        else:
            # Default to SOURCE_PRIORITY
            candidates.sort(key=lambda x: x["priority_weight"], reverse=True)
            return candidates[0]

    def consolidate_all_entities(
        self,
        session: Session,
        entity_type: Optional[str] = None,
    ) -> List[GoldenRecordSummary]:
        """Consolidate golden records for all active Canonical Entities."""
        stmt = select(CanonicalEntity).where(CanonicalEntity.status == "ACTIVE")
        if entity_type:
            stmt = stmt.where(CanonicalEntity.entity_type == entity_type)

        entities = session.execute(stmt).scalars().all()
        summaries = []
        for e in entities:
            s = self.consolidate_entity(session, e.id)
            summaries.append(s)
        return summaries
