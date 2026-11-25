import os
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

    for filepath, dataset_type in sources:
        if not os.path.exists(filepath):
            print(f"[WARN] Không tìm thấy file: {filepath}")
            continue

        with open(filepath, "rb") as f:
            data_bytes = f.read()

        res = run_intake_pipeline(
            file_bytes=data_bytes,
            filename=os.path.basename(filepath),
            dataset_type=dataset_type,
            batch_id="BATCH_2026_01",
            processed_hashes=processed_hashes,
        )
        processed_hashes.add(res["file_hash"])
        db_stats = adapter.save_pipeline_result(res)

        print(
            f"[{os.path.basename(filepath)}] Nhận: {res['stats']['total_received']} | "
            f"Hợp lệ: {res['stats']['valid_count']} | "
            f"Quarantine: {res['stats']['quarantine_count']} | "
            f"DB -> Thêm mới: {db_stats['inserted']}, Cập nhật: {db_stats['updated']}, "
            f"Skipped: {db_stats['skipped']}"
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
            name = payload.get("legal_name") or payload.get("full_name") or ""
            norm_phone = payload.get("_normalized", {}).get("norm_phone", "")
            print(f"  - {r.source_key} | {r.entity_type}/{r.entity_subtype} | {name} | {norm_phone}")

        print(f"\n[QUARANTINE] Tổng bản ghi cách ly trong batch_row_results: {len(quarantined_rows)}")
        for q in quarantined_rows:
            print(f"  - Row {q.row_number} | Key: {q.source_key} | Lý do: {q.quarantine_reason}")
    finally:
        db.close()


if __name__ == "__main__":
    run_full_ingestion()