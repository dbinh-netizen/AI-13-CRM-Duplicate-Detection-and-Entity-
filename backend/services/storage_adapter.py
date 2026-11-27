import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import (
    SourceSystem,
    ImportBatch,
    SourceRecord,
    SourceRecordVersion,
    BatchRowResult,
    SourceIdentifier,
)

logger = logging.getLogger(__name__)


def _sha256_json(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_row_number(row_anchor: str, fallback: int) -> int:
    if ":line_" in row_anchor:
        try:
            return int(row_anchor.split(":line_")[-1])
        except ValueError:
            pass
    return fallback


class StorageAdapter:
    def __init__(self, db: Optional[Session] = None):
        self._owns_session = db is None
        self.db = db or SessionLocal()

    def _get_or_create_source_system(self, source_code: str, entity_pool: str) -> SourceSystem:
        clean_code = (source_code or f"CSV_{entity_pool}").strip()
        existing = (
            self.db.query(SourceSystem)
            .filter(SourceSystem.source_code == clean_code)
            .first()
        )
        if existing:
            if existing.entity_type == entity_pool:
                return existing
            clean_code = f"{clean_code}_{entity_pool}"
            existing_pool = (
                self.db.query(SourceSystem)
                .filter(SourceSystem.source_code == clean_code)
                .first()
            )
            if existing_pool:
                return existing_pool

        sys_obj = SourceSystem(
            source_code=clean_code,
            source_name=f"{clean_code} ({entity_pool})",
            system_type="CSV_IMPORT",
            entity_type=entity_pool,
            is_active=True,
        )
        self.db.add(sys_obj)
        self.db.flush()
        return sys_obj

    def _sync_identifiers(self, source_record_id, norm: dict):
        pairs = [
            ("TAX_ID", norm.get("norm_tax_code")),
            ("PHONE", norm.get("norm_phone")),
            ("EMAIL", norm.get("norm_email")),
        ]
        for ident_type, ident_val in pairs:
            if not ident_val:
                continue
            exists = (
                self.db.query(SourceIdentifier)
                .filter(
                    SourceIdentifier.source_record_id == source_record_id,
                    SourceIdentifier.identifier_type == ident_type,
                    SourceIdentifier.identifier_value == ident_val,
                )
                .first()
            )
            if not exists:
                self.db.add(
                    SourceIdentifier(
                        source_record_id=source_record_id,
                        identifier_type=ident_type,
                        identifier_value=ident_val,
                        is_primary=True,
                    )
                )

    @staticmethod
    def validate_batch_manifest(
        stats: dict,
        file_hash: str,
        manifest: Optional[dict] = None,
    ) -> dict:
        """
        Kiểm tra tính đầy đủ của Batch Manifest và Snapshot trước khi commit vào DB.
        Phát hiện các lỗi:
        - INCOMPLETE_BATCH: Số dòng thực tế nhận được nhỏ hơn số dòng khai báo trong manifest.
        - CHECKSUM_MISMATCH: Mã băm file không khớp với manifest.
        - INCOMPLETE_SNAPSHOT: Snapshot bị đánh dấu chưa hoàn tất (is_complete=False).
        - ROW_RECONCILIATION_MISMATCH: Tổng accepted + quarantined + rejected != total_received.
        """
        manifest = manifest or {}
        errors = []

        total_received = stats.get("total_received", 0)
        valid_count = stats.get("valid_count", 0)
        quarantine_count = stats.get("quarantine_count", 0)
        rejected_count = stats.get("rejected_count", 0)

        if valid_count + quarantine_count + rejected_count != total_received:
            errors.append(
                f"ROW_RECONCILIATION_MISMATCH: received={total_received} != "
                f"accepted({valid_count}) + quarantined({quarantine_count}) + rejected({rejected_count})"
            )

        expected_rows = manifest.get("expected_row_count")
        if expected_rows is not None and total_received != int(expected_rows):
            errors.append(
                f"INCOMPLETE_BATCH: expected_row_count={expected_rows}, actual_received={total_received}"
            )

        expected_checksum = manifest.get("expected_checksum")
        if expected_checksum and expected_checksum.strip().lower() != file_hash.lower():
            errors.append(
                f"CHECKSUM_MISMATCH: expected={expected_checksum}, actual={file_hash}"
            )

        if manifest.get("is_complete") is False:
            errors.append("INCOMPLETE_SNAPSHOT: Snapshot marked as incomplete (is_complete=False)")

        return {
            "is_valid": len(errors) == 0,
            "is_complete_snapshot": len(errors) == 0,
            "snapshot_cutoff": manifest.get("snapshot_cutoff") or datetime.now(timezone.utc).isoformat(),
            "expected_row_count": expected_rows if expected_rows is not None else total_received,
            "actual_row_count": total_received,
            "file_checksum": file_hash,
            "errors": errors,
        }

    def save_pipeline_result(
        self,
        pipeline_result: dict,
        manifest: Optional[dict] = None,
    ) -> dict:
        """
        Lưu kết quả từ run_intake_pipeline() vào DB, kiểm soát Batch Manifest / Snapshot
        và trả về gói thống nhất cho FastAPI.
        """
        entity_pool = pipeline_result.get("dataset_type", "ACCOUNT")
        filename = pipeline_result.get("filename", "unknown.csv")
        file_size = pipeline_result.get("file_size_bytes", 0)
        file_hash = pipeline_result.get("file_hash", "")
        batch_prefix = pipeline_result.get("batch_id", "BATCH_DEFAULT")
        stats = pipeline_result.get("stats", {})

        valid_records = pipeline_result.get("valid_records", [])
        normalized_records = pipeline_result.get("normalized_records", [])
        quarantine_records = pipeline_result.get("quarantine_records", [])

        manifest_check = self.validate_batch_manifest(stats, file_hash, manifest)

        if pipeline_result.get("status") == "SKIPPED_IDEMPOTENT":
            logger.info("[INTAKE] Bỏ qua file trùng lặp trong cùng phiên: %s", filename)
            return self._build_handoff_payload(
                batch_code=f"{batch_prefix}_{entity_pool}_{file_hash[:8]}",
                filename=filename,
                entity_pool=entity_pool,
                status="SKIPPED_IDEMPOTENT",
                stats=stats,
                valid_records=[],
                normalized_records=[],
                quarantine_records=[],
                db_ops={"inserted": 0, "updated": 0, "quarantined": 0, "rejected": 0, "skipped": True},
                manifest_report=manifest_check,
            )

        norm_map = {item["stable_key"]: item for item in normalized_records}
        inserted = 0
        updated = 0
        quarantined = 0
        rejected = stats.get("rejected_count", 0)

        try:
            first_sys_code = (
                valid_records[0]["source_system"]
                if valid_records
                else (quarantine_records[0]["source_system"] if quarantine_records else f"CSV_{entity_pool}")
            )
            primary_sys = self._get_or_create_source_system(first_sys_code, entity_pool)
            batch_code = f"{batch_prefix}_{entity_pool}_{file_hash[:8]}"

            existing_batch = (
                self.db.query(ImportBatch)
                .filter(
                    ImportBatch.source_system_id == primary_sys.id,
                    ImportBatch.file_checksum == file_hash,
                )
                .first()
            )
            if existing_batch and existing_batch.status == "COMPLETED":
                logger.info("[INTAKE] Batch đã tồn tại trong DB (Idempotent): %s", existing_batch.batch_code)
                return self._build_handoff_payload(
                    batch_code=existing_batch.batch_code,
                    filename=filename,
                    entity_pool=entity_pool,
                    status="SKIPPED_IDEMPOTENT",
                    stats=stats,
                    valid_records=[],
                    normalized_records=[],
                    quarantine_records=[],
                    db_ops={"inserted": 0, "updated": 0, "quarantined": 0, "rejected": 0, "skipped": True},
                    manifest_report=manifest_check,
                )

            # Nếu batch/snapshot không đầy đủ -> ghi nhận batch FAILED để audit và chặn ghi vào source_records
            if not manifest_check["is_valid"]:
                error_summary = "; ".join(manifest_check["errors"])
                logger.error("[INCOMPLETE_BATCH] Từ chối nạp batch '%s': %s", batch_code, error_summary)

                if not existing_batch:
                    failed_batch = ImportBatch(
                        batch_code=batch_code,
                        source_system_id=primary_sys.id,
                        batch_type="CSV_INGESTION",
                        file_name=filename,
                        file_checksum=file_hash,
                        file_size_bytes=file_size,
                        total_rows_received=stats.get("total_received", 0),
                        total_rows_valid=0,
                        total_rows_quarantined=0,
                        total_rows_rejected=stats.get("total_received", 0),
                        status="FAILED",
                        notes=error_summary,
                    )
                    self.db.add(failed_batch)
                else:
                    existing_batch.status = "FAILED"
                    existing_batch.notes = error_summary

                self.db.commit()
                return self._build_handoff_payload(
                    batch_code=batch_code,
                    filename=filename,
                    entity_pool=entity_pool,
                    status="FAILED_INCOMPLETE_BATCH",
                    stats=stats,
                    valid_records=[],
                    normalized_records=[],
                    quarantine_records=[],
                    db_ops={
                        "inserted": 0,
                        "updated": 0,
                        "quarantined": 0,
                        "rejected": stats.get("total_received", 0),
                        "skipped": False,
                    },
                    manifest_report=manifest_check,
                )

            if existing_batch and existing_batch.status == "FAILED":
                batch = existing_batch
                batch.total_rows_received = stats.get("total_received", 0)
                batch.total_rows_valid = stats.get("valid_count", 0)
                batch.total_rows_quarantined = stats.get("quarantine_count", 0)
                batch.total_rows_rejected = rejected
                batch.status = "VALIDATING"
                batch.notes = json.dumps(manifest_check, ensure_ascii=False)
            else:
                batch = ImportBatch(
                    batch_code=batch_code,
                    source_system_id=primary_sys.id,
                    batch_type="CSV_INGESTION",
                    file_name=filename,
                    file_checksum=file_hash,
                    file_size_bytes=file_size,
                    total_rows_received=stats.get("total_received", 0),
                    total_rows_valid=stats.get("valid_count", 0),
                    total_rows_quarantined=stats.get("quarantine_count", 0),
                    total_rows_rejected=rejected,
                    status="VALIDATING",
                    notes=json.dumps(manifest_check, ensure_ascii=False),
                )
                self.db.add(batch)
            self.db.flush()

            used_row_numbers = set()
            row_seq = 2

            for valid in valid_records:
                source_key = valid["stable_key"]
                row_sys_code = valid["source_system"]
                entity_subtype = valid["entity_type"]
                raw = valid.get("raw_payload", {})
                norm = norm_map.get(source_key, {})
                flags = valid.get("field_quality_flags", [])

                row_sys = self._get_or_create_source_system(row_sys_code, entity_pool)
                payload_to_store = {
                    **raw,
                    "_normalized": norm,
                    "_quality_flags": flags,
                    "_provenance": {
                        "row_anchor": valid["row_anchor"],
                        "batch_code": batch_code,
                        "batch_id": batch_prefix,
                        "source_system": row_sys_code,
                        "record_type": entity_pool,
                        "entity_subtype": entity_subtype,
                        "source_key": source_key,
                    },
                }
                row_checksum = _sha256_json(raw)
                anchor_hash = hashlib.sha256(valid["row_anchor"].encode("utf-8")).hexdigest()

                existing = (
                    self.db.query(SourceRecord)
                    .filter(
                        SourceRecord.source_system_id == row_sys.id,
                        SourceRecord.entity_type == entity_pool,
                        SourceRecord.source_key == source_key,
                    )
                    .first()
                )

                if existing:
                    existing.import_batch_id = batch.id
                    existing.entity_subtype = entity_subtype
                    existing.status = "ACTIVE"
                    existing.record_payload = payload_to_store
                    db_record = existing

                    current_ver = (
                        self.db.query(SourceRecordVersion)
                        .filter(
                            SourceRecordVersion.source_record_id == db_record.id,
                            SourceRecordVersion.is_current == True,
                        )
                        .first()
                    )
                    next_ver_num = (current_ver.version_number + 1) if current_ver else 1
                    if current_ver:
                        current_ver.is_current = False

                    self.db.add(
                        SourceRecordVersion(
                            source_record_id=db_record.id,
                            version_number=next_ver_num,
                            import_batch_id=batch.id,
                            row_anchor_hash=anchor_hash,
                            raw_payload=raw,
                            checksum=row_checksum,
                            is_current=True,
                        )
                    )
                    updated += 1
                else:
                    db_record = SourceRecord(
                        source_system_id=row_sys.id,
                        entity_type=entity_pool,
                        source_key=source_key,
                        import_batch_id=batch.id,
                        entity_subtype=entity_subtype,
                        status="ACTIVE",
                        record_payload=payload_to_store,
                    )
                    self.db.add(db_record)
                    self.db.flush()

                    self.db.add(
                        SourceRecordVersion(
                            source_record_id=db_record.id,
                            version_number=1,
                            import_batch_id=batch.id,
                            row_anchor_hash=anchor_hash,
                            raw_payload=raw,
                            checksum=row_checksum,
                            is_current=True,
                        )
                    )
                    inserted += 1

                self._sync_identifiers(db_record.id, norm)

                r_num = _extract_row_number(valid["row_anchor"], row_seq)
                while r_num in used_row_numbers:
                    r_num += 1
                used_row_numbers.add(r_num)
                row_seq = r_num + 1

                self.db.add(
                    BatchRowResult(
                        import_batch_id=batch.id,
                        row_number=r_num,
                        source_key=source_key,
                        row_status="VALID",
                        validation_errors=flags if flags else None,
                        raw_row_hash=row_checksum,
                        raw_row_data=raw,
                        source_record_id=db_record.id,
                    )
                )

            for q in quarantine_records:
                raw_q = q.get("raw_payload", {})
                r_num = _extract_row_number(q.get("row_anchor", ""), row_seq)
                while r_num in used_row_numbers:
                    r_num += 1
                used_row_numbers.add(r_num)
                row_seq = r_num + 1

                logger.warning(
                    "[QUARANTINE] File=%s | Anchor=%s | Key=%s | Reason=%s",
                    filename,
                    q.get("row_anchor"),
                    q.get("stable_key"),
                    q.get("reason"),
                )

                self.db.add(
                    BatchRowResult(
                        import_batch_id=batch.id,
                        row_number=r_num,
                        source_key=q.get("stable_key"),
                        row_status="QUARANTINED",
                        quarantine_reason=q.get("reason"),
                        raw_row_hash=_sha256_json(raw_q),
                        raw_row_data=raw_q,
                        source_record_id=None,
                    )
                )
                quarantined += 1

            batch.status = "COMPLETED"
            self.db.commit()

            return self._build_handoff_payload(
                batch_code=batch_code,
                filename=filename,
                entity_pool=entity_pool,
                status="COMPLETED",
                stats=stats,
                valid_records=valid_records,
                normalized_records=normalized_records,
                quarantine_records=quarantine_records,
                db_ops={
                    "inserted": inserted,
                    "updated": updated,
                    "quarantined": quarantined,
                    "rejected": rejected,
                    "skipped": False,
                },
                manifest_report=manifest_check,
            )

        except Exception as e:
            self.db.rollback()
            logger.error("[INTAKE_ERROR] Lỗi khi lưu batch từ file '%s': %s", filename, e, exc_info=True)
            raise
        finally:
            if self._owns_session:
                self.db.close()

    def reconcile_batch_with_db(self, batch_code: str) -> dict:
        """
        Đối soát độc lập một batch giữa bảng import_batches, batch_row_results,
        source_records và source_record_versions trong Database.
        """
        session = SessionLocal() if self._owns_session else self.db
        try:
            batch = (
                session.query(ImportBatch)
                .filter(ImportBatch.batch_code == batch_code)
                .first()
            )
            if not batch:
                raise ValueError(f"Không tìm thấy batch_code: {batch_code}")

            row_results = (
                session.query(BatchRowResult)
                .filter(BatchRowResult.import_batch_id == batch.id)
                .all()
            )
            db_valid_rows = [r for r in row_results if r.row_status == "VALID"]
            db_quarantined_rows = [r for r in row_results if r.row_status == "QUARANTINED"]
            db_rejected_rows = [r for r in row_results if r.row_status == "REJECTED"]

            source_records = (
                session.query(SourceRecord)
                .filter(SourceRecord.import_batch_id == batch.id)
                .all()
            )
            versions = (
                session.query(SourceRecordVersion)
                .filter(SourceRecordVersion.import_batch_id == batch.id)
                .all()
            )

            provenance_intact = True
            missing_provenance_keys = []
            for rec in source_records:
                payload = rec.record_payload or {}
                prov = payload.get("_provenance", {})
                norm = payload.get("_normalized", {})
                has_raw = any(k in payload for k in ("legal_name", "full_name"))
                has_prov = all([
                    prov.get("batch_code") == batch.batch_code,
                    prov.get("source_system"),
                    prov.get("record_type") == rec.entity_type,
                    prov.get("source_key") == rec.source_key,
                    bool(norm),
                    has_raw,
                ])
                if not has_prov:
                    provenance_intact = False
                    missing_provenance_keys.append(rec.source_key)

            counts_balanced = (
                batch.total_rows_received
                == (batch.total_rows_valid + batch.total_rows_quarantined + batch.total_rows_rejected)
                and len(db_valid_rows) == batch.total_rows_valid
                and len(db_quarantined_rows) == batch.total_rows_quarantined
            )

            return {
                "batch_code": batch.batch_code,
                "file_name": batch.file_name,
                "batch_status": batch.status,
                "received": batch.total_rows_received,
                "accepted": batch.total_rows_valid,
                "quarantined": batch.total_rows_quarantined,
                "rejected": batch.total_rows_rejected,
                "db_batch_row_results_total": len(row_results),
                "db_source_records_count": len(source_records),
                "db_versions_count": len(versions),
                "counts_balanced": counts_balanced,
                "provenance_intact": provenance_intact,
                "missing_provenance_keys": missing_provenance_keys,
            }
        finally:
            if self._owns_session:
                session.close()

    @staticmethod
    def _build_handoff_payload(
        batch_code: str,
        filename: str,
        entity_pool: str,
        status: str,
        stats: dict,
        valid_records: list,
        normalized_records: list,
        quarantine_records: list,
        db_ops: dict,
        manifest_report: Optional[dict] = None,
    ) -> dict:
        """Cấu trúc JSON chuẩn để bàn giao trực tiếp cho FastAPI & Matching Engine."""
        return {
            "batch_code": batch_code,
            "filename": filename,
            "entity_pool": entity_pool,
            "status": status,
            "manifest_report": manifest_report or {},
            "batch_stats": {
                **stats,
                **db_ops,
            },
            "valid_records": valid_records,
            "normalized_records": normalized_records,
            "quarantine_report": {
                "total_quarantined": len(quarantine_records),
                "reasons_breakdown": stats.get("quarantine_reasons", {}),
                "items": quarantine_records,
            },
            # Giữ các khóa phẳng để tương thích ngược với run_ingestion.py
            "inserted": db_ops["inserted"],
            "updated": db_ops["updated"],
            "quarantined": db_ops["quarantined"],
            "rejected": db_ops.get("rejected", 0),
            "skipped": db_ops["skipped"],
        }