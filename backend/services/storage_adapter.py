import json
import hashlib
import logging
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

    def save_pipeline_result(self, pipeline_result: dict) -> dict:
        """
        Lưu kết quả từ run_intake_pipeline() vào DB và trả về gói thống nhất cho FastAPI.
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
                db_ops={"inserted": 0, "updated": 0, "quarantined": 0, "skipped": True},
            )

        norm_map = {item["stable_key"]: item for item in normalized_records}
        inserted = 0
        updated = 0
        quarantined = 0

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
                    db_ops={"inserted": 0, "updated": 0, "quarantined": 0, "skipped": True},
                )

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
                total_rows_rejected=0,
                status="VALIDATING",
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
                    "skipped": False,
                },
            )

        except Exception as e:
            self.db.rollback()
            logger.error("[INTAKE_ERROR] Lỗi khi lưu batch từ file '%s': %s", filename, e, exc_info=True)
            raise
        finally:
            if self._owns_session:
                self.db.close()

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
    ) -> dict:
        """Cấu trúc JSON chuẩn để bàn giao trực tiếp cho FastAPI & Matching Engine."""
        return {
            "batch_code": batch_code,
            "filename": filename,
            "entity_pool": entity_pool,
            "status": status,
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
            "skipped": db_ops["skipped"],
        }