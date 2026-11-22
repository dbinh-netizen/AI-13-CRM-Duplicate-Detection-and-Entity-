"""Intake and Row-Level Validation Service for Milestone P2.5.

Sub-milestone: P2.5 - STEP 1: IMPORT & VALIDATE THREE SOURCE FILES
Module: backend.canonical.intake_service

Responsibilities:
1. Ingestion of 3 CSV source files:
   - File A: Account CRM_A
   - File B: Account CRM_B
   - File C: Contact CRM_C
2. Row-level validation:
   - UTF-8 decoding check
   - Mandatory source_key validation
   - In-batch duplicate key detection
   - Data hygiene & malformed field flagging
   - Row categorization: ACCEPTED, QUARANTINED, REJECTED
3. Persistence:
   - ImportBatch with checksum and row counts
   - SourceRecord (immutable payload)
   - SourceRecordVersion (SCD Type 2 snapshot anchor)
   - BatchRowResult for granular auditability
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from backend.models.intake import BatchRowResult, ImportBatch, SourceRecord, SourceRecordVersion, SourceSystem

logger = logging.getLogger(__name__)


class RowValidationResult(BaseModel):
    row_number: int
    source_key: Optional[str]
    row_status: str  # ACCEPTED, QUARANTINED, REJECTED
    validation_errors: List[str] = Field(default_factory=list)
    raw_data: Dict[str, Any]
    source_record_id: Optional[str] = None


class BatchIngestionReport(BaseModel):
    batch_id: str
    batch_code: str
    source_code: str
    entity_type: str
    file_name: str
    file_checksum: str
    total_rows_received: int
    total_rows_valid: int
    total_rows_quarantined: int
    total_rows_rejected: int
    row_results: List[RowValidationResult] = Field(default_factory=list)


class IntakeService:
    """Enterprise-grade file intake and row validation engine."""

    def ingest_csv_file(
        self,
        session: Session,
        file_path_or_bytes: Union[str, Path, bytes],
        source_code: str,
        entity_type: str = "ACCOUNT",
        file_name: Optional[str] = None,
        actor_id: Optional[Union[str, UUID]] = None,
        **kwargs: Any,
    ) -> BatchIngestionReport:
        """
        Ingest a CSV source file (File A, B, or C) with rigorous row-level validation.
        """
        pool = kwargs.get("entity_pool", entity_type)
        entity_pool = str(pool).upper().strip()
        if entity_pool not in ("ACCOUNT", "CONTACT"):
            raise ValueError(f"Invalid entity_type '{entity_type}'. Must be ACCOUNT or CONTACT.")

        # Read content bytes
        if isinstance(file_path_or_bytes, (str, Path)):
            p = Path(file_path_or_bytes)
            if not p.exists():
                raise FileNotFoundError(f"Input file not found at '{file_path_or_bytes}'.")
            content_bytes = p.read_bytes()
            if not file_name:
                file_name = p.name
        else:
            content_bytes = file_path_or_bytes
            if not file_name:
                file_name = f"upload_{source_code}_{uuid.uuid4().hex[:6]}.csv"

        file_checksum = hashlib.sha256(content_bytes).hexdigest()
        file_size_bytes = len(content_bytes)

        # 1. Resolve or register SourceSystem
        source_sys = session.execute(
            select(SourceSystem).where(SourceSystem.source_code == source_code)
        ).scalar_one_or_none()

        if not source_sys:
            source_sys = SourceSystem(
                id=uuid.uuid4(),
                source_code=source_code,
                source_name=f"System {source_code}",
                system_type="CRM",
                entity_type=entity_pool,
                is_active=True,
            )
            session.add(source_sys)
            session.flush()

        # Check existing batch with same checksum (Idempotent replay)
        existing_batch = session.execute(
            select(ImportBatch).where(
                and_(
                    ImportBatch.source_system_id == source_sys.id,
                    ImportBatch.file_checksum == file_checksum,
                )
            )
        ).scalar_one_or_none()

        if existing_batch:
            logger.info("Found existing batch %s for file %s. Returning existing.", existing_batch.batch_code, file_name)
            # Fetch existing row results
            row_records = session.execute(
                select(BatchRowResult).where(BatchRowResult.import_batch_id == existing_batch.id)
            ).scalars().all()

            results = [
                RowValidationResult(
                    row_number=r.row_number,
                    source_key=r.source_key,
                    row_status=r.row_status,
                    validation_errors=r.validation_errors or [],
                    raw_data=r.raw_row_data or {},
                    source_record_id=str(r.source_record_id) if r.source_record_id else None,
                )
                for r in row_records
            ]

            return BatchIngestionReport(
                batch_id=str(existing_batch.id),
                batch_code=existing_batch.batch_code,
                source_code=source_code,
                entity_type=entity_pool,
                file_name=file_name,
                file_checksum=file_checksum,
                total_rows_received=existing_batch.total_rows_received,
                total_rows_valid=existing_batch.total_rows_valid,
                total_rows_quarantined=existing_batch.total_rows_quarantined,
                total_rows_rejected=existing_batch.total_rows_rejected,
                row_results=results,
            )

        # 2. Decode UTF-8
        try:
            text_data = content_bytes.decode("utf-8-sig")  # Handles BOM gracefully
        except UnicodeDecodeError as e:
            raise ValueError(f"File '{file_name}' violates UTF-8 encoding requirement: {e}")

        # 3. Parse CSV rows
        reader = csv.DictReader(io.StringIO(text_data))
        if not reader.fieldnames:
            raise ValueError(f"File '{file_name}' contains no readable header.")

        now_dt = datetime.now(timezone.utc)
        batch_id = uuid.uuid4()
        batch_code = f"BATCH-{source_code}-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        batch = ImportBatch(
            id=batch_id,
            batch_code=batch_code,
            source_system_id=source_sys.id,
            batch_type="FULL",
            file_name=file_name,
            file_checksum=file_checksum,
            file_size_bytes=file_size_bytes,
            status="VALIDATING",
            imported_at=now_dt,
            imported_by=UUID(str(actor_id)) if actor_id else None,
            created_at=now_dt,
        )
        session.add(batch)
        session.flush()

        seen_keys_in_batch = set()
        total_received = 0
        total_valid = 0
        total_quarantined = 0
        total_rejected = 0
        row_validation_reports: List[RowValidationResult] = []

        for idx, row in enumerate(reader, start=1):
            total_received += 1
            row_errors: List[str] = []
            row_status = "VALID"

            # Clean raw keys and values
            clean_row = {str(k).strip(): str(v).strip() for k, v in row.items() if k is not None}
            row_json_str = json.dumps(clean_row, sort_keys=True, ensure_ascii=False)
            row_hash = hashlib.sha256(row_json_str.encode("utf-8")).hexdigest()

            # Identify source_key
            source_key = clean_row.get("source_key") or clean_row.get("id") or clean_row.get("code")

            if not source_key:
                row_status = "REJECTED"
                row_errors.append("Mandatory field 'source_key' is missing or empty.")
                total_rejected += 1
            elif source_key in seen_keys_in_batch:
                row_status = "QUARANTINED"
                row_errors.append(f"Duplicate 'source_key' '{source_key}' detected within same batch.")
                total_quarantined += 1
            else:
                seen_keys_in_batch.add(source_key)

                # Entity-specific validation checks
                if entity_pool == "ACCOUNT":
                    company_name = clean_row.get("company_name") or clean_row.get("legal_name") or clean_row.get("primary_name")
                    if not company_name:
                        row_status = "QUARANTINED"
                        row_errors.append("Missing essential account field 'company_name' / 'legal_name'.")
                        total_quarantined += 1
                elif entity_pool == "CONTACT":
                    contact_name = clean_row.get("contact_name") or clean_row.get("full_name") or clean_row.get("name")
                    if not contact_name:
                        row_status = "QUARANTINED"
                        row_errors.append("Missing essential contact field 'contact_name' / 'full_name'.")
                        total_quarantined += 1

            source_record_id = None
            if row_status == "VALID":
                total_valid += 1
                # Check if SourceRecord already exists for this source system + key
                existing_rec = session.execute(
                    select(SourceRecord).where(
                        and_(
                            SourceRecord.source_system_id == source_sys.id,
                            SourceRecord.entity_type == entity_pool,
                            SourceRecord.source_key == source_key,
                        )
                    )
                ).scalar_one_or_none()

                if existing_rec:
                    source_record_id = existing_rec.id
                    existing_rec.record_payload = clean_row
                    existing_rec.updated_at = now_dt
                else:
                    source_record_id = uuid.uuid4()
                    new_rec = SourceRecord(
                        id=source_record_id,
                        source_system_id=source_sys.id,
                        entity_type=entity_pool,
                        source_key=source_key,
                        import_batch_id=batch.id,
                        entity_subtype=clean_row.get("entity_subtype") or clean_row.get("entity_type") or "COMPANY",
                        status="ACTIVE",
                        record_payload=clean_row,
                        created_at=now_dt,
                        updated_at=now_dt,
                    )
                    session.add(new_rec)
                    session.flush()

                # Add SourceRecordVersion (Version 1 or increment)
                ver_count = session.execute(
                    select(SourceRecordVersion).where(SourceRecordVersion.source_record_id == source_record_id)
                ).scalars().all()
                next_ver = len(ver_count) + 1

                rec_ver = SourceRecordVersion(
                    id=uuid.uuid4(),
                    source_record_id=source_record_id,
                    version_number=next_ver,
                    import_batch_id=batch.id,
                    row_anchor_hash=row_hash,
                    raw_payload=clean_row,
                    checksum=row_hash,
                    effective_from=now_dt,
                    is_current=True,
                    created_at=now_dt,
                )
                session.add(rec_ver)

            # Record BatchRowResult
            batch_row = BatchRowResult(
                id=uuid.uuid4(),
                import_batch_id=batch.id,
                row_number=idx,
                source_key=source_key,
                row_status=row_status,
                validation_errors={"errors": row_errors} if row_errors else None,
                quarantine_reason="; ".join(row_errors) if row_errors and row_status != "VALID" else None,
                raw_row_hash=row_hash,
                raw_row_data=clean_row,
                source_record_id=source_record_id,
                created_at=now_dt,
            )
            session.add(batch_row)

            row_validation_reports.append(
                RowValidationResult(
                    row_number=idx,
                    source_key=source_key,
                    row_status=row_status,
                    validation_errors=row_errors,
                    raw_data=clean_row,
                    source_record_id=str(source_record_id) if source_record_id else None,
                )
            )

        # Update batch summary
        batch.total_rows_received = total_received
        batch.total_rows_valid = total_valid
        batch.total_rows_quarantined = total_quarantined
        batch.total_rows_rejected = total_rejected
        batch.status = "COMPLETED"
        session.commit()

        logger.info(
            "Batch %s completed: %d received, %d valid, %d quarantined, %d rejected",
            batch_code, total_received, total_valid, total_quarantined, total_rejected
        )

        return BatchIngestionReport(
            batch_id=str(batch.id),
            batch_code=batch.batch_code,
            source_code=source_code,
            entity_type=entity_pool,
            file_name=file_name,
            file_checksum=file_checksum,
            total_rows_received=total_received,
            total_rows_valid=total_valid,
            total_rows_quarantined=total_quarantined,
            total_rows_rejected=total_rejected,
            row_results=row_validation_reports,
        )

    # Alias for convenience
    ingest_file = ingest_csv_file
