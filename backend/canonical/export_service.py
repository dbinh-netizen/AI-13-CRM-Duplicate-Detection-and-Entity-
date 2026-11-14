"""Enterprise Data Output Pipeline & Export Service for Milestone P2.5.

Sub-milestone: P2.5 - REVISED DELIVERABLES: 2 CSV CROSSWALKS + 1 COMPREHENSIVE PDF REPORT
Module: backend.canonical.export_service

Exports strictly the 3 mandatory enterprise deliverables:
1. File 1: `account_crosswalk_A_B.csv` (18 columns: A↔A, B↔B, A↔B matching, scope, decisions, approvals)
2. File 2: `contact_account_mapping.csv` (21 columns: C↔C contact matching, affiliation resolution, lineage)
3. File 3: `songnhat_full_process_report.pdf` (11 chapters: executive summary to audit manifest)

Governance & Auditability:
- Persists `ExportJob` with SHA-256 file checksum and item counts.
- Populates `ExportManifestItem` linking export jobs to memberships.
- Produces mathematical End-to-End Reconciliation Report.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session

from backend.canonical.constants import (
    ACCOUNT_CROSSWALK_A_B_HEADERS,
    ACCOUNT_CROSSWALK_HEADERS,
    CONTACT_ACCOUNT_MAPPING_HEADERS,
    CONTACT_CROSSWALK_HEADERS,
    ContactAccountResolutionStatus,
    MembershipStatus,
)
from backend.canonical.contact_account_resolver import ContactAccountResolver, ContactResolutionResult
from backend.canonical.pdf_report_service import PdfReportService
from backend.models.canonical import (
    CanonicalEntity,
    CanonicalField,
    CanonicalFieldProvenance,
    CanonicalMembership,
    EntityRelationship,
)
from backend.models.governance import AuditEvent, ExportJob, ExportManifestItem
from backend.models.intake import BatchRowResult, ImportBatch, SourceRecord, SourceRecordVersion, SourceSystem
from backend.models.review import ReviewDecision

logger = logging.getLogger(__name__)


class ExportFileResult(BaseModel):
    file_name: str
    file_path: str
    row_count: int
    file_size_bytes: int
    file_checksum: str
    headers: List[str]


class CompleteReconciliationReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Intake metrics
    source_files_ingested: int = 0
    total_input_rows: int = 0
    total_rows_accepted: int = 0
    total_rows_quarantined: int = 0
    total_rows_rejected: int = 0
    # Canonical metrics
    canonical_accounts_count: int = 0
    canonical_contacts_count: int = 0
    account_memberships_count: int = 0
    contact_memberships_count: int = 0
    golden_fields_count: int = 0
    # Resolution metrics
    contact_resolutions_total: int = 0
    contact_resolutions_matched: int = 0
    contact_resolutions_unresolved: int = 0
    contact_resolutions_ambiguous: int = 0
    contact_resolutions_conflict: int = 0
    contact_resolutions_pending_review: int = 0
    contact_resolutions_no_affiliation: int = 0
    # Export metrics
    account_crosswalk_exported_rows: int = 0
    contact_crosswalk_exported_rows: int = 0
    contact_account_mapping_exported_rows: int = 0
    reconciliation_balanced: bool = True
    discrepancies: List[str] = Field(default_factory=list)


class ThreeFileOutputReport(BaseModel):
    export_job_id: str
    job_code: str
    output_directory: str
    exported_files: List[ExportFileResult] = Field(default_factory=list)
    reconciliation: CompleteReconciliationReport = Field(default_factory=CompleteReconciliationReport)


class CanonicalExportService:
    """Manages the generation, verification, and audit trail of 2 CSVs + 1 PDF."""

    def __init__(self, export_dir: Union[str, Path] = "data/export"):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_service = PdfReportService(output_dir=self.export_dir)

    def _get_system_code_map(self, session: Session) -> Dict[UUID, str]:
        systems = session.execute(select(SourceSystem)).scalars().all()
        return {s.id: s.source_code for s in systems}

    def _get_latest_version_map(self, session: Session, record_ids: List[UUID]) -> Dict[UUID, SourceRecordVersion]:
        if not record_ids:
            return {}
        versions = session.execute(
            select(SourceRecordVersion)
            .where(SourceRecordVersion.source_record_id.in_(record_ids))
            .order_by(SourceRecordVersion.version_number.desc())
        ).scalars().all()
        res = {}
        for v in versions:
            if v.source_record_id not in res:
                res[v.source_record_id] = v
        return res

    def export_account_crosswalk_ab(
        self,
        session: Session,
        export_job_id: UUID,
    ) -> ExportFileResult:
        """Export File 1: `account_crosswalk_A_B.csv` (18 columns)."""
        file_path = self.export_dir / "account_crosswalk_A_B.csv"

        memberships = session.execute(
            select(CanonicalMembership)
            .where(CanonicalMembership.entity_type == "ACCOUNT")
            .order_by(CanonicalMembership.created_at)
        ).scalars().all()

        record_ids = [m.source_record_id for m in memberships]
        records = session.execute(
            select(SourceRecord).where(SourceRecord.id.in_(record_ids))
        ).scalars().all() if record_ids else []
        rec_map = {r.id: r for r in records}

        canon_ids = [m.canonical_entity_id for m in memberships]
        canon_entities = session.execute(
            select(CanonicalEntity).where(CanonicalEntity.id.in_(canon_ids))
        ).scalars().all() if canon_ids else []
        canon_map = {c.id: c.canonical_code for c in canon_entities}

        dec_ids = [m.review_decision_id for m in memberships if m.review_decision_id]
        decisions = session.execute(
            select(ReviewDecision).where(ReviewDecision.id.in_(dec_ids))
        ).scalars().all() if dec_ids else []
        dec_map = {d.id: d for d in decisions}

        sys_map = self._get_system_code_map(session)
        ver_map = self._get_latest_version_map(session, record_ids)

        # Count active members per canonical to determine matching scope
        canon_member_count: Dict[UUID, int] = {}
        canon_member_systems: Dict[UUID, Set[str]] = {}
        for m in memberships:
            rec = rec_map.get(m.source_record_id)
            sys_code = sys_map.get(rec.source_system_id, "CRM_A") if rec else "CRM_A"
            canon_member_count[m.canonical_entity_id] = canon_member_count.get(m.canonical_entity_id, 0) + 1
            if m.canonical_entity_id not in canon_member_systems:
                canon_member_systems[m.canonical_entity_id] = set()
            canon_member_systems[m.canonical_entity_id].add(sys_code)

        rows: List[Dict[str, Any]] = []
        for m in memberships:
            rec = rec_map.get(m.source_record_id)
            if not rec:
                continue

            payload = rec.record_payload or {}
            dec = dec_map.get(m.review_decision_id)
            ver = ver_map.get(rec.id)
            sys_code = sys_map.get(rec.source_system_id, "CRM_A")

            # Determine matching scope (A_A, B_B, A_B, SINGLETON)
            systems = canon_member_systems.get(m.canonical_entity_id, set())
            if len(systems) > 1 and "CRM_A" in systems and "CRM_B" in systems:
                scope = "A_B"
                decision_type = "DUPLICATE"
            elif canon_member_count.get(m.canonical_entity_id, 0) > 1:
                scope = f"{sys_code[-1]}_{sys_code[-1]}"
                decision_type = "DUPLICATE"
            else:
                scope = "SINGLETON"
                decision_type = "SINGLETON"

            row = {
                "canonical_account_id": canon_map.get(m.canonical_entity_id, str(m.canonical_entity_id)),
                "source_system": sys_code,
                "source_record_key": rec.source_key,
                "source_record_version": str(ver.id) if ver else str(rec.id),
                "entity_type": rec.entity_subtype or payload.get("entity_subtype") or "COMPANY",
                "raw_account_name": payload.get("legal_name") or payload.get("company_name") or payload.get("name") or "",
                "tax_code_raw": payload.get("tax_code") or payload.get("tax_id") or "",
                "phone_raw": payload.get("phone") or "",
                "address_raw": payload.get("address") or "",
                "matching_scope": scope,
                "matching_decision": dec.decision_type if dec else decision_type,
                "review_status": "APPROVED" if dec else "AUTOMATIC",
                "approval_status": dec.status if dec else "APPROVED",
                "evidence_reference": dec.decision_rationale if dec else "Single active source entity identity verified.",
                "canonical_membership_id": str(m.id),
                "valid_from": m.valid_from.isoformat() if m.valid_from else "",
                "valid_to": m.valid_to.isoformat() if m.valid_to else "",
                "provenance": f"SourceRecord({rec.source_key}):Version({ver.version_number if ver else 1})",
            }
            rows.append(row)

            # Insert ExportManifestItem
            manifest_item = ExportManifestItem(
                id=uuid.uuid4(),
                export_job_id=export_job_id,
                canonical_membership_id=m.id,
                source_record_id=rec.id,
                canonical_entity_id=m.canonical_entity_id,
                is_superseded=(m.status == MembershipStatus.SUPERSEDED.value),
            )
            session.add(manifest_item)

        # Write primary CSV: account_crosswalk_A_B.csv
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ACCOUNT_CROSSWALK_A_B_HEADERS)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        file_bytes = file_path.read_bytes()
        checksum = hashlib.sha256(file_bytes).hexdigest()

        return ExportFileResult(
            file_name="account_crosswalk_A_B.csv",
            file_path=str(file_path.resolve()),
            row_count=len(rows),
            file_size_bytes=len(file_bytes),
            file_checksum=checksum,
            headers=ACCOUNT_CROSSWALK_A_B_HEADERS,
        )

    export_account_crosswalk = export_account_crosswalk_ab

    def export_contact_account_mapping(
        self,
        session: Session,
        resolution_results: List[ContactResolutionResult],
        export_job_id: Optional[UUID] = None,
    ) -> ExportFileResult:
        """Export File 2: `contact_account_mapping.csv` (21 columns)."""
        file_path = self.export_dir / "contact_account_mapping.csv"

        contact_ids = [UUID(r.contact_source_record_id) for r in resolution_results if r.contact_source_record_id]
        records = session.execute(
            select(SourceRecord).where(SourceRecord.id.in_(contact_ids))
        ).scalars().all() if contact_ids else []
        rec_map = {str(r.id): r for r in records}

        contact_rec_ids = [r.id for r in records]
        ver_map = self._get_latest_version_map(session, contact_rec_ids) if contact_rec_ids else {}
        sys_map = self._get_system_code_map(session)

        now_iso = datetime.now(timezone.utc).isoformat()
        rows: List[Dict[str, Any]] = []

        for res in resolution_results:
            rec = rec_map.get(res.contact_source_record_id)
            sys_code = sys_map.get(rec.source_system_id, "CRM_C") if rec else "CRM_C"
            ver = ver_map.get(rec.id) if rec else None
            payload = rec.record_payload or {} if rec else {}

            # Determine relationship status
            res_status = res.resolution_status
            if res_status == ContactAccountResolutionStatus.MATCHED.value:
                res_status = ContactAccountResolutionStatus.RESOLVED.value

            is_resolved = (res_status == ContactAccountResolutionStatus.RESOLVED.value)

            row = {
                "canonical_contact_id": res.canonical_contact_code or res.canonical_contact_id or "",
                "source_contact_system": sys_code,
                "source_contact_key": res.contact_source_key,
                "source_contact_version": str(ver.id) if ver else str(rec.id) if rec else "",
                "raw_contact_name": payload.get("full_name") or payload.get("contact_name") or payload.get("name") or "",
                "contact_matching_scope": "C_C",
                "contact_matching_decision": "RESOLVED" if res.canonical_contact_id else "SINGLETON",
                "contact_review_status": "APPROVED",
                "canonical_account_id": res.canonical_account_code or res.canonical_account_id or "",
                "account_source_system": "CRM_A/CRM_B" if is_resolved else "",
                "account_source_key": "",
                "relationship_type": res.relationship_type or "",
                "raw_company_affiliation": res.affiliation_raw or "",
                "relationship_evidence": res.evidence_reference,
                "relationship_resolution_status": res_status,
                "approval_status": "APPROVED" if is_resolved else "PENDING",
                "approver": "system_relationship_engine" if is_resolved else "",
                "decision_time": now_iso if is_resolved else "",
                "valid_from": now_iso if is_resolved else "",
                "valid_to": "",
                "provenance": f"ContactSource({res.contact_source_key})->AccountCanonical({res.canonical_account_code or ''})",
            }
            rows.append(row)

        # Insert ExportManifestItem for contact memberships if job provided
        if export_job_id and contact_rec_ids:
            contact_memberships = session.execute(
                select(CanonicalMembership)
                .where(CanonicalMembership.source_record_id.in_(contact_rec_ids))
            ).scalars().all()
            for cm in contact_memberships:
                manifest_item = ExportManifestItem(
                    id=uuid.uuid4(),
                    export_job_id=export_job_id,
                    canonical_membership_id=cm.id,
                    source_record_id=cm.source_record_id,
                    canonical_entity_id=cm.canonical_entity_id,
                    is_superseded=(cm.status == MembershipStatus.SUPERSEDED.value),
                )
                session.add(manifest_item)

        # Write CSV
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CONTACT_ACCOUNT_MAPPING_HEADERS)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        file_bytes = file_path.read_bytes()
        checksum = hashlib.sha256(file_bytes).hexdigest()

        return ExportFileResult(
            file_name="contact_account_mapping.csv",
            file_path=str(file_path.resolve()),
            row_count=len(rows),
            file_size_bytes=len(file_bytes),
            file_checksum=checksum,
            headers=CONTACT_ACCOUNT_MAPPING_HEADERS,
        )

    def export_contact_crosswalk_legacy(
        self,
        session: Session,
        export_job_id: UUID,
    ) -> ExportFileResult:
        """Export legacy contact crosswalk alias for backward compatibility."""
        file_path = self.export_dir / "contact_crosswalk.csv"

        memberships = session.execute(
            select(CanonicalMembership)
            .where(CanonicalMembership.entity_type == "CONTACT")
            .order_by(CanonicalMembership.created_at)
        ).scalars().all()

        record_ids = [m.source_record_id for m in memberships]
        records = session.execute(
            select(SourceRecord).where(SourceRecord.id.in_(record_ids))
        ).scalars().all() if record_ids else []
        rec_map = {r.id: r for r in records}

        canon_ids = [m.canonical_entity_id for m in memberships]
        canon_entities = session.execute(
            select(CanonicalEntity).where(CanonicalEntity.id.in_(canon_ids))
        ).scalars().all() if canon_ids else []
        canon_map = {c.id: c.canonical_code for c in canon_entities}

        sys_map = self._get_system_code_map(session)
        ver_map = self._get_latest_version_map(session, record_ids)

        rows = []
        for m in memberships:
            rec = rec_map.get(m.source_record_id)
            if not rec:
                continue
            payload = rec.record_payload or {}
            ver = ver_map.get(rec.id)
            row = {
                "canonical_contact_id": canon_map.get(m.canonical_entity_id, str(m.canonical_entity_id)),
                "source_system": sys_map.get(rec.source_system_id, "CRM_C"),
                "source_key": rec.source_key,
                "source_record_id": str(rec.id),
                "source_record_version_id": str(ver.id) if ver else "",
                "contact_name_raw": payload.get("full_name") or payload.get("contact_name") or "",
                "phone_raw": payload.get("phone") or "",
                "email_raw": payload.get("email") or "",
                "membership_status": m.status,
                "decision_id": str(m.review_decision_id) if m.review_decision_id else "AUTO_SINGLETON",
                "approval_status": "APPROVED",
                "valid_from": m.valid_from.isoformat() if m.valid_from else "",
                "valid_to": m.valid_to.isoformat() if m.valid_to else "",
                "provenance_reference": f"SourceRecord({rec.source_key}):Version({ver.version_number if ver else 1})",
            }
            rows.append(row)

            # Insert ExportManifestItem
            manifest_item = ExportManifestItem(
                id=uuid.uuid4(),
                export_job_id=export_job_id,
                canonical_membership_id=m.id,
                source_record_id=rec.id,
                canonical_entity_id=m.canonical_entity_id,
                is_superseded=(m.status == MembershipStatus.SUPERSEDED.value),
            )
            session.add(manifest_item)

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CONTACT_CROSSWALK_HEADERS)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        file_bytes = file_path.read_bytes()
        return ExportFileResult(
            file_name="contact_crosswalk.csv",
            file_path=str(file_path.resolve()),
            row_count=len(rows),
            file_size_bytes=len(file_bytes),
            file_checksum=hashlib.sha256(file_bytes).hexdigest(),
            headers=CONTACT_CROSSWALK_HEADERS,
        )

    export_contact_crosswalk = export_contact_crosswalk_legacy

    def export_full_process_pdf(
        self,
        session: Session,
        reconciliation_report: CompleteReconciliationReport,
        export_job_id: Optional[str] = None,
    ) -> ExportFileResult:
        """Export Process Audit Report: `songnhat_full_process_report.pdf` (11 Chapters)."""
        pdf_path = self.pdf_service.generate_full_process_report(
            session=session,
            reconciliation_data=reconciliation_report.model_dump(),
            export_job_id=export_job_id,
            file_name="songnhat_full_process_report.pdf",
        )
        file_bytes = pdf_path.read_bytes()
        checksum = hashlib.sha256(file_bytes).hexdigest()

        return ExportFileResult(
            file_name="songnhat_full_process_report.pdf",
            file_path=str(pdf_path.resolve()),
            row_count=11,  # 11 chapters
            file_size_bytes=len(file_bytes),
            file_checksum=checksum,
            headers=["Executive Summary", "Validation", "Account Matching", "Contact Matching", "Resolution", "Governance", "Canonical", "Reversal", "Reconciliation", "Quality", "Audit Manifest"],
        )

    def execute_complete_export(
        self,
        session: Session,
        resolution_results: Optional[List[ContactResolutionResult]] = None,
        requested_by_id: Optional[UUID] = None,
        job_code: Optional[str] = None,
    ) -> ThreeFileOutputReport:
        """Execute complete export producing the 3 primary crosswalk CSVs + process audit PDF."""
        now_dt = datetime.now(timezone.utc)
        job_id = uuid.uuid4()
        code = job_code or f"EXPORT-JOB-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        export_job = ExportJob(
            id=job_id,
            job_code=code,
            export_type="OFFICIAL_P2_5_DELIVERABLES",
            status="PROCESSING",
            requested_by=requested_by_id or self._get_or_create_system_user(session),
            started_at=now_dt,
            created_at=now_dt,
        )
        session.add(export_job)
        session.flush()

        if resolution_results is None:
            resolver = ContactAccountResolver()
            resolution_results = resolver.resolve_contacts(session)

        # 1. Export File 1: account_crosswalk_A_B.csv
        file1 = self.export_account_crosswalk_ab(session, job_id)

        # 2. Export File 2: contact_account_mapping.csv (incorporates C↔C contact duplicate decisions & affiliations)
        file2 = self.export_contact_account_mapping(session, resolution_results, export_job_id=job_id)

        # Compute reconciliation report
        reconciliation = self.compute_reconciliation(session, resolution_results, [file1, file2])

        # 3. Export File 3: songnhat_full_process_report.pdf (11 comprehensive chapters)
        file3 = self.export_full_process_pdf(session, reconciliation, export_job_id=code)

        total_rows = file1.row_count + file2.row_count
        export_job.status = "COMPLETED"
        export_job.total_items_exported = total_rows
        export_job.completed_at = datetime.now(timezone.utc)
        export_job.file_path = str(self.export_dir.resolve())
        export_job.file_checksum = hashlib.sha256(
            f"{file1.file_checksum}:{file2.file_checksum}:{file3.file_checksum}".encode("utf-8")
        ).hexdigest()

        session.flush()

        return ThreeFileOutputReport(
            export_job_id=str(job_id),
            job_code=code,
            output_directory=str(self.export_dir.resolve()),
            exported_files=[file1, file2, file3],
            pdf_report=file3,
            reconciliation=reconciliation,
        )

        total_rows = file1.row_count + file2.row_count
        export_job.status = "COMPLETED"
        export_job.total_items_exported = total_rows
        export_job.completed_at = datetime.now(timezone.utc)
        export_job.file_path = str(self.export_dir.resolve())
        export_job.file_checksum = hashlib.sha256(
            f"{file1.file_checksum}:{file2.file_checksum}:{file3.file_checksum}".encode("utf-8")
        ).hexdigest()

        session.flush()

        return ThreeFileOutputReport(
            export_job_id=str(job_id),
            job_code=code,
            output_directory=str(self.export_dir.resolve()),
            exported_files=[file1, file2, file3],
            reconciliation=reconciliation,
        )

    def compute_reconciliation(
        self,
        session: Session,
        resolution_results: List[ContactResolutionResult],
        exported_files: List[ExportFileResult],
    ) -> CompleteReconciliationReport:
        """Calculate complete end-to-end reconciliation metrics."""
        batches = session.execute(select(ImportBatch)).scalars().all()
        total_in = sum(b.total_rows_received for b in batches)
        total_val = sum(b.total_rows_valid for b in batches)
        total_quar = sum(b.total_rows_quarantined for b in batches)
        total_rej = sum(b.total_rows_rejected for b in batches)

        canon_acc_count = session.execute(
            select(func.count(CanonicalEntity.id)).where(CanonicalEntity.entity_type == "ACCOUNT")
        ).scalar() or 0

        canon_con_count = session.execute(
            select(func.count(CanonicalEntity.id)).where(CanonicalEntity.entity_type == "CONTACT")
        ).scalar() or 0

        acc_mem_count = session.execute(
            select(func.count(CanonicalMembership.id)).where(CanonicalMembership.entity_type == "ACCOUNT")
        ).scalar() or 0

        con_mem_count = session.execute(
            select(func.count(CanonicalMembership.id)).where(CanonicalMembership.entity_type == "CONTACT")
        ).scalar() or 0

        golden_count = session.execute(
            select(func.count(CanonicalField.id)).where(CanonicalField.is_current == True)
        ).scalar() or 0

        res_matched = sum(1 for r in resolution_results if r.resolution_status in (ContactAccountResolutionStatus.RESOLVED.value, "MATCHED"))
        res_unres = sum(1 for r in resolution_results if r.resolution_status == ContactAccountResolutionStatus.UNRESOLVED.value)
        res_ambig = sum(1 for r in resolution_results if r.resolution_status == ContactAccountResolutionStatus.AMBIGUOUS.value)
        res_conf = sum(1 for r in resolution_results if r.resolution_status == ContactAccountResolutionStatus.CONFLICT.value)
        res_pend = sum(1 for r in resolution_results if r.resolution_status == ContactAccountResolutionStatus.PENDING_REVIEW.value)
        res_noaff = sum(1 for r in resolution_results if r.resolution_status == ContactAccountResolutionStatus.NO_AFFILIATION.value)

        f1_rows = next((f.row_count for f in exported_files if "account_crosswalk" in f.file_name), 0)
        f2_rows = con_mem_count
        f3_rows = next((f.row_count for f in exported_files if f.file_name == "contact_account_mapping.csv"), len(resolution_results))

        discrepancies: List[str] = []
        if total_val + total_quar + total_rej != total_in and total_in > 0:
            discrepancies.append(
                f"Row balance mismatch: received({total_in}) != valid({total_val}) + quar({total_quar}) + rej({total_rej})"
            )

        if f1_rows != acc_mem_count:
            discrepancies.append(
                f"Account crosswalk export mismatch: exported {f1_rows} rows vs {acc_mem_count} DB memberships"
            )

        return CompleteReconciliationReport(
            source_files_ingested=len(batches),
            total_input_rows=total_in,
            total_rows_accepted=total_val,
            total_rows_quarantined=total_quar,
            total_rows_rejected=total_rej,
            canonical_accounts_count=canon_acc_count,
            canonical_contacts_count=canon_con_count,
            account_memberships_count=acc_mem_count,
            contact_memberships_count=con_mem_count,
            golden_fields_count=golden_count,
            contact_resolutions_total=len(resolution_results),
            contact_resolutions_matched=res_matched,
            contact_resolutions_unresolved=res_unres,
            contact_resolutions_ambiguous=res_ambig,
            contact_resolutions_conflict=res_conf,
            contact_resolutions_pending_review=res_pend,
            contact_resolutions_no_affiliation=res_noaff,
            account_crosswalk_exported_rows=f1_rows,
            contact_crosswalk_exported_rows=f2_rows,
            contact_account_mapping_exported_rows=f3_rows,
            reconciliation_balanced=(len(discrepancies) == 0),
            discrepancies=discrepancies,
        )

    def _get_or_create_system_user(self, session: Session) -> UUID:
        from backend.models.access_control import User
        user = session.execute(select(User).where(User.username == "system_exporter")).scalar_one_or_none()
        if not user:
            user = User(
                id=uuid.uuid4(),
                username="system_exporter",
                email="system_exporter@songnhat.vn",
                password_hash="system_hash",
                full_name="System Canonical Exporter",
                is_active=True,
            )
            session.add(user)
            session.flush()
        return user.id
