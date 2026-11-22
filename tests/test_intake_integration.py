import sqlite3
import unittest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models import Base, SourceRecord, SourceRecordVersion, BatchRowResult, ImportBatch
from backend.services.intake_processor import run_intake_pipeline
from backend.services.storage_adapter import StorageAdapter


# --- TEST FIXTURES ---
FIXTURE_MIXED_ACCOUNTS_CSV = """source_key,source_system,entity_type,legal_name,tax_code,phone,email,address
ACC-9001,CRM_OLD,COMPANY,Công ty TNHH Công Nghệ Sao Việt,0312345678,+84909111222,info@saoviet.vn,12 Nguyễn Huệ Q1
ACC-9002,CRM_OLD,CONTACT,Dòng sai entity_type cho file account,0312345679,0909111223,err@saoviet.vn,Hà Nội
,CRM_OLD,COMPANY,Dòng thiếu source_key,0312345680,0909111224,nokey@saoviet.vn,Đà Nẵng
ACC-9003,CRM_OLD,BRANCH,Chi nhánh Sao Việt - Hà Nội,0312345678-001,0909111225,hn@saoviet.vn,Cầu Giấy HN
ACC-9003,CRM_OLD,BRANCH,Chi nhánh Sao Việt - Sai lệch dữ liệu,0312345678-002,0909111226,hn2@saoviet.vn,Ba Đình HN
ACC-9004,CRM_OLD,COMPANY,Công ty Bị Cảnh Báo SĐT,INVALID_TAX,12345,bad-email,Cần Thơ
""".encode("utf-8")


class TestIntakeIntegration(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @sa.event.listens_for(self.engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, connection_record):
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.close()

        Base.metadata.create_all(bind=self.engine)
        self.TestSession = sessionmaker(bind=self.engine)
        self.db = self.TestSession()

    def tearDown(self):
        self.db.close()

    def test_valid_quarantine_provenance_and_rerun_same_batch(self):
        # 1. Chạy lần 1 với fixture hỗn hợp (có dòng hợp lệ, dòng cảnh báo và dòng lỗi quarantine)
        pipeline_res = run_intake_pipeline(
            file_bytes=FIXTURE_MIXED_ACCOUNTS_CSV,
            filename="fixture_mixed_accounts.csv",
            dataset_type="ACCOUNT",
            batch_id="BATCH_TEST_W04",
        )

        adapter = StorageAdapter(db=self.db)
        with self.assertLogs("backend.services.storage_adapter", level="WARNING") as log_cm:
            handoff = adapter.save_pipeline_result(pipeline_res)

        # Kiểm tra log lỗi/cảnh báo quarantine đã được ghi nhận
        self.assertTrue(any("[QUARANTINE]" in msg for msg in log_cm.output))

        # Kiểm tra cấu trúc bàn giao FastAPI
        self.assertEqual(handoff["status"], "COMPLETED")
        self.assertEqual(handoff["batch_stats"]["inserted"], 2)       # ACC-9001, ACC-9004
        self.assertEqual(handoff["batch_stats"]["quarantined"], 4)    # 1 sai entity_type, 1 thiếu key, 2 xung đột ACC-9003
        self.assertEqual(handoff["quarantine_report"]["total_quarantined"], 4)

        # 2. Kiểm tra bảo toàn raw values, source keys và row provenance trong DB
        rec_9001 = self.db.query(SourceRecord).filter_by(source_key="ACC-9001").first()
        self.assertIsNotNone(rec_9001)
        self.assertEqual(rec_9001.record_payload["phone"], "+84909111222")  # Raw giữ nguyên +84
        self.assertEqual(rec_9001.record_payload["_normalized"]["norm_phone"], "0909111222")
        self.assertIn("fixture_mixed_accounts.csv:line_2", rec_9001.record_payload["_provenance"]["row_anchor"])

        ver_9001 = self.db.query(SourceRecordVersion).filter_by(source_record_id=rec_9001.id).first()
        self.assertIsNotNone(ver_9001)
        self.assertEqual(ver_9001.raw_payload["legal_name"], "Công ty TNHH Công Nghệ Sao Việt")

        quarantined_db = self.db.query(BatchRowResult).filter_by(row_status="QUARANTINED").all()
        self.assertEqual(len(quarantined_db), 4)

        # 3. Test chạy lại cùng batch (Idempotency)
        rerun_handoff = adapter.save_pipeline_result(pipeline_res)
        self.assertEqual(rerun_handoff["status"], "SKIPPED_IDEMPOTENT")
        self.assertTrue(rerun_handoff["skipped"])
        self.assertEqual(self.db.query(SourceRecord).count(), 2)
        self.assertEqual(self.db.query(ImportBatch).count(), 1)


if __name__ == "__main__":
    unittest.main()