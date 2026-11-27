import os
import hashlib
from backend.database import engine, SessionLocal
from backend.models import Base, SourceRecord, BatchRowResult
from backend.services.intake_processor import run_intake_pipeline
from backend.services.storage_adapter import StorageAdapter


def run_full_ingestion():
    Base.metadata.create_all(bind=engine)

    sources = [
        ("data/sample_csv/accounts_source_a.csv", "ACCOUNT"),
        ("data/sample_csv/accounts_source_b.csv", "ACCOUNT"),
        ("data/sample_csv/contacts_source.csv", "CONTACT"),
    ]

    processed_hashes = set()
    adapter = StorageAdapter()
    reconciliation_reports = []

    print("=== [W05] BẮT ĐẦU KIỂM SOÁT CSV INTAKE, BATCH MANIFEST & PROVENANCE ===")
    for filepath, dataset_type in sources:
        if not os.path.exists(filepath):
            print(f"[WARN] Không tìm thấy file: {filepath}")
            continue

        with open(filepath, "rb") as f:
            data_bytes = f.read()

        # Tạo manifest chuẩn từ file nguồn trước khi nạp
        lines = [ln for ln in data_bytes.decode("utf-8-sig").splitlines() if ln.strip()]
        expected_rows = max(len(lines) - 1, 0)
        manifest = {
            "expected_row_count": expected_rows,
            "expected_checksum": hashlib.sha256(data_bytes).hexdigest(),
            "is_complete": True,
        }

        res = run_intake_pipeline(
            file_bytes=data_bytes,
            filename=os.path.basename(filepath),
            dataset_type=dataset_type,
            batch_id="BATCH_2026_W05",
            processed_hashes=processed_hashes,
        )
        processed_hashes.add(res["file_hash"])
        db_stats = adapter.save_pipeline_result(res, manifest=manifest)

        print(
            f"[{os.path.basename(filepath)}] Trạng thái: {db_stats['status']} | "
            f"Nhận: {res['stats']['total_received']} | "
            f"Accepted: {res['stats']['valid_count']} | "
            f"Quarantined: {res['stats']['quarantine_count']} | "
            f"Rejected: {db_stats['rejected']} | "
            f"DB Inserted: {db_stats['inserted']}, Updated: {db_stats['updated']}, Skipped: {db_stats['skipped']}"
        )

        rec_report = adapter.reconcile_batch_with_db(db_stats["batch_code"])
        reconciliation_reports.append(rec_report)

    print("\n=== BẢNG ĐỐI SOÁT DỮ LIỆU CSV INTAKE <-> DATABASE (SYNTHETIC) ===")
    for r in reconciliation_reports:
        print(
            f"  - Batch: {r['batch_code']} ({r['file_name']}) | Status: {r['batch_status']} | "
            f"Received={r['received']} (Accepted={r['accepted']}, Quarantined={r['quarantined']}, Rejected={r['rejected']}) | "
            f"DB SourceRecords={r['db_source_records_count']} | Balanced={r['counts_balanced']} | ProvenanceOK={r['provenance_intact']}"
        )

    db = SessionLocal()
    try:
        rows = db.query(SourceRecord).all()
        quarantined_rows = (
            db.query(BatchRowResult)
            .filter(BatchRowResult.row_status == "QUARANTINED")
            .all()
        )
        print(f"\n[DONE] Tổng bản ghi trong source_records: {len(rows)}")
        for r in rows:
            payload = r.record_payload or {}
            prov = payload.get("_provenance", {})
            name = payload.get("legal_name") or payload.get("full_name") or ""
            norm_phone = payload.get("_normalized", {}).get("norm_phone", "")
            print(
                f"  - Key={r.source_key} | Sys={prov.get('source_system')} | Type={r.entity_type}/{r.entity_subtype} | "
                f"Batch={prov.get('batch_code')} | Name={name} | NormPhone={norm_phone}"
            )

        print(f"\n[QUARANTINE] Tổng bản ghi cách ly trong batch_row_results: {len(quarantined_rows)}")
        for q in quarantined_rows:
            print(f"  - Row {q.row_number} | Key: {q.source_key} | Lý do: {q.quarantine_reason}")
    finally:
        db.close()

    print("\n[NOTE] Dữ liệu trên là bộ synthetic phục vụ kiểm thử tích hợp luồng CSV Intake - DB - Backend;")
    print("       KHÔNG sử dụng số liệu synthetic này để công bố precision/recall thực tế của mô hình.")


if __name__ == "__main__":
    run_full_ingestion()