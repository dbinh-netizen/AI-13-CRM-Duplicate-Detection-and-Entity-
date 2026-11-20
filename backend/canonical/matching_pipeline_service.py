"""Multi-step Matching Pipeline Service for Milestone P2.5.

Sub-milestone: P2.5 - STEP 2 & STEP 3 MATCHING ORCHESTRATION
Module: backend.canonical.matching_pipeline_service

Coordinates the 4 discrete matching runs across the 3 ingested data sources:
1. Account Internal A (A ↔ A): Detect duplicates strictly within CRM_A.
2. Account Internal B (B ↔ B): Detect duplicates strictly within CRM_B.
3. Account Cross-Source (A ↔ B): Detect duplicates between CRM_A and CRM_B.
4. Contact Internal C (C ↔ C): Detect duplicates strictly within CRM_C.

Pool segregation:
- ACCOUNT pool (CRM_A, CRM_B) and CONTACT pool (CRM_C) are NEVER mixed in duplicate detection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.matching.blocking_engine import (
    EntityPool,
    IdentifierItem,
    MultiPathBlockingEngine,
    SourceRecordInput,
    clean_address_tokens,
    clean_email_address,
    clean_phone_number,
    clean_tax_id,
    clean_vietnamese_company_name,
    extract_tax_root,
    remove_vietnamese_accents,
)
from backend.matching.matching_engine import (
    MatchingEngine,
    MatchingPipelineResult,
    MatchingRunRequest,
    MatchingRunType,
)
from backend.models.intake import (
    BatchRowResult,
    ImportBatch,
    MatchingRun,
    SourceRecord,
    SourceRecordVersion,
    SourceSystem,
)

logger = logging.getLogger(__name__)


def build_source_record_input(
    record: SourceRecord,
    system_code: str,
    latest_version: Optional[SourceRecordVersion] = None,
) -> SourceRecordInput:
    """Transform a database SourceRecord into a normalized SourceRecordInput."""
    payload = record.record_payload or {}
    pool = record.entity_type.upper()

    identifiers: List[IdentifierItem] = []

    if pool == "ACCOUNT":
        raw_name = (
            payload.get("legal_name")
            or payload.get("company_name")
            or payload.get("primary_name")
            or payload.get("name")
            or ""
        )
        tax_code_raw = payload.get("tax_code") or payload.get("tax_id") or ""
        cleaned_tax = clean_tax_id(tax_code_raw)
        tax_root = extract_tax_root(cleaned_tax)
        if cleaned_tax:
            identifiers.append(
                IdentifierItem(
                    identifier_type="TAX_ID",
                    identifier_value=cleaned_tax,
                    is_primary=True,
                    entity_level=payload.get("entity_subtype") or payload.get("entity_type") or "COMPANY",
                )
            )

        phone_raw = payload.get("phone") or payload.get("phone_number") or ""
        clean_phone = clean_phone_number(phone_raw)
        if clean_phone:
            identifiers.append(
                IdentifierItem(
                    identifier_type="PHONE",
                    identifier_value=clean_phone,
                    is_primary=False,
                )
            )

        email_raw = payload.get("email") or payload.get("contact_email") or ""
        clean_email = clean_email_address(email_raw)
        if clean_email:
            identifiers.append(
                IdentifierItem(
                    identifier_type="EMAIL",
                    identifier_value=clean_email,
                    is_primary=False,
                )
            )

        address_raw = payload.get("address") or payload.get("street_address") or ""
        address_clean = clean_address_tokens(address_raw)
        normalized_name = clean_vietnamese_company_name(raw_name)

        return SourceRecordInput(
            source_record_id=str(record.id),
            source_system_code=system_code,
            entity_type="ACCOUNT",
            source_key=record.source_key,
            version_id=str(latest_version.id) if latest_version else None,
            version_number=latest_version.version_number if latest_version else 1,
            raw_payload=payload,
            identifiers=identifiers,
            tax_code=cleaned_tax if cleaned_tax else None,
            tax_code_root=tax_root if tax_root else None,
            primary_name=raw_name,
            normalized_name=normalized_name,
            name_tokens=normalized_name.split() if normalized_name else [],
            phone_clean=clean_phone if clean_phone else None,
            phones_clean=[clean_phone] if clean_phone else [],
            email_clean=clean_email if clean_email else None,
            emails_clean=[clean_email] if clean_email else [],
            address_normalized=address_clean if address_clean else None,
            province_city=payload.get("province_city"),
            district=payload.get("district"),
            street_ward=payload.get("street_ward"),
        )
    else:
        # CONTACT pool
        raw_name = (
            payload.get("full_name")
            or payload.get("contact_name")
            or payload.get("name")
            or ""
        )
        norm_name = remove_vietnamese_accents(raw_name).strip().upper()

        phone_raw = payload.get("phone") or payload.get("phone_number") or ""
        clean_phone = clean_phone_number(phone_raw)
        if clean_phone:
            identifiers.append(
                IdentifierItem(
                    identifier_type="PHONE",
                    identifier_value=clean_phone,
                    is_primary=True,
                )
            )

        email_raw = payload.get("email") or payload.get("contact_email") or ""
        clean_email = clean_email_address(email_raw)
        if clean_email:
            identifiers.append(
                IdentifierItem(
                    identifier_type="EMAIL",
                    identifier_value=clean_email,
                    is_primary=False,
                )
            )

        return SourceRecordInput(
            source_record_id=str(record.id),
            source_system_code=system_code,
            entity_type="CONTACT",
            source_key=record.source_key,
            version_id=str(latest_version.id) if latest_version else None,
            version_number=latest_version.version_number if latest_version else 1,
            raw_payload=payload,
            identifiers=identifiers,
            primary_name=raw_name,
            normalized_name=norm_name,
            name_tokens=norm_name.split() if norm_name else [],
            phone_clean=clean_phone if clean_phone else None,
            phones_clean=[clean_phone] if clean_phone else [],
            email_clean=clean_email if clean_email else None,
            emails_clean=[clean_email] if clean_email else [],
        )


class StepMatchingSummary(BaseModel):
    step_name: str
    run_id: str
    run_code: str
    entity_pool: str
    records_scanned: int
    candidate_pairs_found: int
    duration_seconds: float
    status: str


class FullPipelineMatchingReport(BaseModel):
    pipeline_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    account_internal_a: Optional[StepMatchingSummary] = None
    account_internal_b: Optional[StepMatchingSummary] = None
    account_cross_ab: Optional[StepMatchingSummary] = None
    contact_internal_c: Optional[StepMatchingSummary] = None
    total_candidate_pairs: int = 0
    total_duration_seconds: float = 0.0


class CanonicalMatchingPipelineService:
    """Coordinates the 4 discrete matching runs across CRM_A, CRM_B, and CRM_C."""

    def __init__(self, engine: Optional[MatchingEngine] = None):
        self.engine = engine or MatchingEngine()

    def _fetch_records_for_systems(
        self,
        session: Session,
        system_codes: List[str],
        entity_type: str,
    ) -> List[SourceRecordInput]:
        """Fetch active source records for given system codes and pool."""
        # Query systems
        systems = session.execute(
            select(SourceSystem).where(SourceSystem.source_code.in_(system_codes))
        ).scalars().all()
        if not systems:
            return []

        sys_id_map = {s.id: s.source_code for s in systems}

        records = session.execute(
            select(SourceRecord).where(
                and_(
                    SourceRecord.source_system_id.in_(list(sys_id_map.keys())),
                    SourceRecord.entity_type == entity_type,
                    SourceRecord.status == "ACTIVE",
                )
            )
        ).scalars().all()

        record_inputs: List[SourceRecordInput] = []
        for r in records:
            sys_code = sys_id_map.get(r.source_system_id, "UNKNOWN")
            # Get latest version if available
            latest_version = session.execute(
                select(SourceRecordVersion)
                .where(SourceRecordVersion.source_record_id == r.id)
                .order_by(SourceRecordVersion.version_number.desc())
            ).scalars().first()

            inp = build_source_record_input(r, sys_code, latest_version)
            record_inputs.append(inp)

        return record_inputs

    def run_account_internal_a(
        self,
        session: Session,
        actor_username: str = "system_canonical_pipeline",
    ) -> MatchingPipelineResult:
        """Run A ↔ A: Duplicate detection strictly within CRM_A."""
        logger.info("Executing matching step: Account Internal CRM_A (A ↔ A)")
        records = self._fetch_records_for_systems(session, ["CRM_A"], "ACCOUNT")
        run_code = f"RUN-CANON-A-A-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        req = MatchingRunRequest(
            run_code=run_code,
            entity_pool="ACCOUNT",
            run_type=MatchingRunType.FULL,
            source_system_codes=["CRM_A"],
            actor_username=actor_username,
        )
        return self.engine.execute_matching_run(
            request=req,
            records=records,
            session=session,
        )

    def run_account_internal_b(
        self,
        session: Session,
        actor_username: str = "system_canonical_pipeline",
    ) -> MatchingPipelineResult:
        """Run B ↔ B: Duplicate detection strictly within CRM_B."""
        logger.info("Executing matching step: Account Internal CRM_B (B ↔ B)")
        records = self._fetch_records_for_systems(session, ["CRM_B"], "ACCOUNT")
        run_code = f"RUN-CANON-B-B-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        req = MatchingRunRequest(
            run_code=run_code,
            entity_pool="ACCOUNT",
            run_type=MatchingRunType.FULL,
            source_system_codes=["CRM_B"],
            actor_username=actor_username,
        )
        return self.engine.execute_matching_run(
            request=req,
            records=records,
            session=session,
        )

    def run_account_cross_source_ab(
        self,
        session: Session,
        actor_username: str = "system_canonical_pipeline",
    ) -> MatchingPipelineResult:
        """Run A ↔ B: Cross-source duplicate detection between CRM_A and CRM_B."""
        logger.info("Executing matching step: Account Cross-Source (A ↔ B)")
        records = self._fetch_records_for_systems(session, ["CRM_A", "CRM_B"], "ACCOUNT")
        run_code = f"RUN-CANON-A-B-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        req = MatchingRunRequest(
            run_code=run_code,
            entity_pool="ACCOUNT",
            run_type=MatchingRunType.FULL,
            source_system_codes=["CRM_A", "CRM_B"],
            actor_username=actor_username,
        )
        return self.engine.execute_matching_run(
            request=req,
            records=records,
            session=session,
        )

    def run_contact_internal_c(
        self,
        session: Session,
        actor_username: str = "system_canonical_pipeline",
    ) -> MatchingPipelineResult:
        """Run C ↔ C: Duplicate detection strictly within CRM_C."""
        logger.info("Executing matching step: Contact Internal CRM_C (C ↔ C)")
        records = self._fetch_records_for_systems(session, ["CRM_C"], "CONTACT")
        run_code = f"RUN-CANON-C-C-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        req = MatchingRunRequest(
            run_code=run_code,
            entity_pool="CONTACT",
            run_type=MatchingRunType.FULL,
            source_system_codes=["CRM_C"],
            actor_username=actor_username,
        )
        return self.engine.execute_matching_run(
            request=req,
            records=records,
            session=session,
        )

    def execute_all_matching_steps(
        self,
        session: Session,
        actor_username: str = "system_canonical_pipeline",
    ) -> FullPipelineMatchingReport:
        """Execute all 4 steps in sequential order."""
        report = FullPipelineMatchingReport()
        t0 = datetime.now(timezone.utc)

        # 1. A ↔ A
        res_a = self.run_account_internal_a(session, actor_username)
        report.account_internal_a = StepMatchingSummary(
            step_name="Account Internal CRM_A (A ↔ A)",
            run_id=res_a.matching_run_id,
            run_code=res_a.run_code,
            entity_pool="ACCOUNT",
            records_scanned=res_a.reconciliation.records_scanned,
            candidate_pairs_found=res_a.total_candidates,
            duration_seconds=res_a.total_duration_seconds,
            status=res_a.status,
        )

        # 2. B ↔ B
        res_b = self.run_account_internal_b(session, actor_username)
        report.account_internal_b = StepMatchingSummary(
            step_name="Account Internal CRM_B (B ↔ B)",
            run_id=res_b.matching_run_id,
            run_code=res_b.run_code,
            entity_pool="ACCOUNT",
            records_scanned=res_b.reconciliation.records_scanned,
            candidate_pairs_found=res_b.total_candidates,
            duration_seconds=res_b.total_duration_seconds,
            status=res_b.status,
        )

        # 3. A ↔ B
        res_ab = self.run_account_cross_source_ab(session, actor_username)
        report.account_cross_ab = StepMatchingSummary(
            step_name="Account Cross-Source (A ↔ B)",
            run_id=res_ab.matching_run_id,
            run_code=res_ab.run_code,
            entity_pool="ACCOUNT",
            records_scanned=res_ab.reconciliation.records_scanned,
            candidate_pairs_found=res_ab.total_candidates,
            duration_seconds=res_ab.total_duration_seconds,
            status=res_ab.status,
        )

        # 4. C ↔ C
        res_c = self.run_contact_internal_c(session, actor_username)
        report.contact_internal_c = StepMatchingSummary(
            step_name="Contact Internal CRM_C (C ↔ C)",
            run_id=res_c.matching_run_id,
            run_code=res_c.run_code,
            entity_pool="CONTACT",
            records_scanned=res_c.reconciliation.records_scanned,
            candidate_pairs_found=res_c.total_candidates,
            duration_seconds=res_c.total_duration_seconds,
            status=res_c.status,
        )

        report.completed_at = datetime.now(timezone.utc)
        report.total_candidate_pairs = (
            res_a.total_candidates
            + res_b.total_candidates
            + res_ab.total_candidates
            + res_c.total_candidates
        )
        report.total_duration_seconds = (report.completed_at - t0).total_seconds()
        return report
