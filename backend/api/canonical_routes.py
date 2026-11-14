"""RESTful API Endpoints for Milestone P2.5 - Canonical Entity & Three-File Pipeline.

Module: backend.api.canonical_routes
Prefix: /canonical
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.canonical.activation_service import CanonicalActivationService
from backend.canonical.contact_account_resolver import ContactAccountResolver
from backend.canonical.export_service import CanonicalExportService
from backend.canonical.golden_record_service import GoldenRecordService
from backend.canonical.intake_service import IntakeService
from backend.canonical.matching_pipeline_service import CanonicalMatchingPipelineService
from backend.database import get_db
from backend.models.canonical import CanonicalEntity, CanonicalMembership

router = APIRouter(prefix="/canonical", tags=["Canonical & Three-File Export API"])


class IngestFileRequest(BaseModel):
    file_path: str
    source_code: str  # CRM_A, CRM_B, CRM_C
    entity_pool: str  # ACCOUNT, CONTACT


class ActivateSingletonsRequest(BaseModel):
    entity_pool: str  # ACCOUNT, CONTACT
    source_system_codes: Optional[List[str]] = None


@router.post("/ingest")
def ingest_source_file(
    payload: IngestFileRequest,
    db: Session = Depends(get_db),
):
    """Ingest and validate a source CSV file with row-level categorization."""
    intake = IntakeService()
    try:
        report = intake.ingest_file(
            session=db,
            file_path_or_bytes=payload.file_path,
            source_code=payload.source_code,
            entity_pool=payload.entity_pool,
        )
        db.commit()
        return {
            "status": "SUCCESS",
            "report": report.model_dump(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/match-all")
def run_all_matching_steps(
    db: Session = Depends(get_db),
):
    """Run sequential 4-step matching: A↔A, B↔B, A↔B, C↔C."""
    matcher = CanonicalMatchingPipelineService()
    try:
        report = matcher.execute_all_matching_steps(db)
        db.commit()
        return {
            "status": "SUCCESS",
            "report": report.model_dump(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activate-singletons")
def activate_singletons(
    payload: ActivateSingletonsRequest,
    db: Session = Depends(get_db),
):
    """Auto-activate distinct/singleton records into 1-to-1 Canonical Entities."""
    activator = CanonicalActivationService()
    try:
        res = activator.activate_singletons(
            session=db,
            entity_type=payload.entity_pool,
            source_system_codes=payload.source_system_codes,
        )
        db.commit()
        return {
            "status": "SUCCESS",
            "summary": res.model_dump(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resolve-contacts")
def resolve_contacts_to_accounts(
    db: Session = Depends(get_db),
):
    """Resolve all contacts' company affiliations against approved Canonical Accounts."""
    resolver = ContactAccountResolver()
    try:
        results = resolver.resolve_contacts(db)
        db.commit()
        return {
            "status": "SUCCESS",
            "total_contacts_resolved": len(results),
            "results": [r.model_dump() for r in results],
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/golden-records")
def consolidate_golden_records(
    entity_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Execute field-level survivorship to build Golden Records."""
    golden_svc = GoldenRecordService()
    try:
        summaries = golden_svc.consolidate_all_entities(db, entity_type=entity_type)
        db.commit()
        return {
            "status": "SUCCESS",
            "entities_consolidated": len(summaries),
            "summaries": [s.model_dump() for s in summaries],
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
def export_three_files(
    export_dir: str = "data/export",
    db: Session = Depends(get_db),
):
    """Produce the 3 mandatory output files and reconciliation report."""
    export_svc = CanonicalExportService(export_dir=export_dir)
    try:
        report = export_svc.execute_complete_export(db)
        db.commit()
        return {
            "status": "SUCCESS",
            "export_job_id": report.export_job_id,
            "job_code": report.job_code,
            "output_directory": report.output_directory,
            "files": [f.model_dump() for f in report.exported_files],
            "reconciliation": report.reconciliation.model_dump(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads")
def get_available_downloads(export_dir: str = "data/export"):
    """Returns downloadable metadata and API URLs for the 3 frontend download buttons."""
    exp_path = Path(export_dir)
    f1_path = exp_path / "account_crosswalk_A_B.csv"
    f2_path = exp_path / "contact_account_mapping.csv"
    f3_path = exp_path / "songnhat_full_process_report.pdf"

    return {
        "status": "SUCCESS",
        "description": "3 nút tải xuống kết quả đầu ra chính thức theo yêu cầu RFP SongNhat CRM",
        "buttons": [
            {
                "button_id": "btn_download_account_crosswalk",
                "label": "Tải xuống Account Crosswalk (CSV)",
                "file_name": "account_crosswalk_A_B.csv",
                "download_url": "/api/canonical/download/account-crosswalk",
                "format": "CSV",
                "columns": 18,
                "exists": f1_path.exists(),
                "size_bytes": f1_path.stat().st_size if f1_path.exists() else 0,
                "description": "Ánh xạ toàn bộ Doanh nghiệp CRM_A & CRM_B sang Canonical Account ID (18 cột)",
            },
            {
                "button_id": "btn_download_contact_mapping",
                "label": "Tải xuống Contact Account Mapping (CSV)",
                "file_name": "contact_account_mapping.csv",
                "download_url": "/api/canonical/download/contact-account-mapping",
                "format": "CSV",
                "columns": 21,
                "exists": f2_path.exists(),
                "size_bytes": f2_path.stat().st_size if f2_path.exists() else 0,
                "description": "Kết quả trùng Contact C↔C & Liên kết nơi công tác sang Canonical Account ID (21 cột)",
            },
            {
                "button_id": "btn_download_process_pdf",
                "label": "Tải xuống Hồ sơ Hợp nhất & Bằng chứng (PDF)",
                "file_name": "songnhat_full_process_report.pdf",
                "download_url": "/api/canonical/download/process-report-pdf",
                "format": "PDF",
                "chapters": 11,
                "exists": f3_path.exists(),
                "size_bytes": f3_path.stat().st_size if f3_path.exists() else 0,
                "description": "Hồ sơ thẩm định toàn diện quá trình hợp nhất thực thể & dữ liệu vàng (11 Chương)",
            },
        ],
    }


@router.get("/download/account-crosswalk")
def download_account_crosswalk(export_dir: str = "data/export"):
    """Nút 1: Tải xuống file account_crosswalk_A_B.csv."""
    path = Path(export_dir) / "account_crosswalk_A_B.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File account_crosswalk_A_B.csv chưa được xuất. Hãy chạy /canonical/export trước.")
    return FileResponse(
        path=str(path.resolve()),
        filename="account_crosswalk_A_B.csv",
        media_type="text/csv",
    )


@router.get("/download/contact-account-mapping")
def download_contact_account_mapping(export_dir: str = "data/export"):
    """Nút 2: Tải xuống file contact_account_mapping.csv."""
    path = Path(export_dir) / "contact_account_mapping.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File contact_account_mapping.csv chưa được xuất. Hãy chạy /canonical/export trước.")
    return FileResponse(
        path=str(path.resolve()),
        filename="contact_account_mapping.csv",
        media_type="text/csv",
    )


@router.get("/download/process-report-pdf")
def download_process_report_pdf(export_dir: str = "data/export"):
    """Nút 3: Tải xuống file songnhat_full_process_report.pdf."""
    path = Path(export_dir) / "songnhat_full_process_report.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File songnhat_full_process_report.pdf chưa được xuất. Hãy chạy /canonical/export trước.")
    return FileResponse(
        path=str(path.resolve()),
        filename="songnhat_full_process_report.pdf",
        media_type="application/pdf",
    )


@router.get("/entities")
def get_canonical_entities(
    entity_type: Optional[str] = None,
    status: Optional[str] = "ACTIVE",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List Canonical Entities with their membership count."""
    query = db.query(CanonicalEntity)
    if entity_type:
        query = query.filter(CanonicalEntity.entity_type == entity_type)
    if status:
        query = query.filter(CanonicalEntity.status == status)

    entities = query.limit(limit).all()
    results = []
    for e in entities:
        mem_count = (
            db.query(CanonicalMembership)
            .filter(CanonicalMembership.canonical_entity_id == e.id)
            .count()
        )
        results.append({
            "id": str(e.id),
            "canonical_code": e.canonical_code,
            "entity_type": e.entity_type,
            "status": e.status,
            "membership_count": mem_count,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })
    return {"total": len(results), "entities": results}
