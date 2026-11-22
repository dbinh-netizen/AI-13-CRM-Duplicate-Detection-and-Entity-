from backend.models.intake import (
    SourceRecord,
    SourceRecordVersion,
)


def test_intake_import_csv_success(client, db_session, tmp_path):
    # 1. Tạo CSV thử nghiệm
    csv_path = tmp_path / "test_accounts.csv"

    csv_path.write_text(
        "source_key,legal_name,tax_code\n"
        "ACC-TEST-101,Cong ty Test A,0101234567\n"
        "ACC-TEST-102,Cong ty Test B,0107654321\n",
        encoding="utf-8",
    )

    # 2. Gọi Intake API
    response = client.post(
        "/api/canonical/ingest",
        json={
            "file_path": str(csv_path),
            "source_code": "TEST_CRM",
            "entity_pool": "ACCOUNT",
        },
    )

    # 3. Kiểm tra response
    assert response.status_code == 200, response.text

    body = response.json()

    assert body["status"] == "SUCCESS"

    report = body["report"]

    assert report["total_rows_received"] == 2
    assert report["total_rows_valid"] == 2
    assert report["total_rows_quarantined"] == 0
    assert report["total_rows_rejected"] == 0

    # 4. Kiểm tra dữ liệu trong Database test
    records = db_session.query(SourceRecord).all()

    assert len(records) == 2

    source_keys = {record.source_key for record in records}

    assert source_keys == {
        "ACC-TEST-101",
        "ACC-TEST-102",
    }

    # 5. Kiểm tra SourceRecordVersion
    versions = db_session.query(SourceRecordVersion).all()

    assert len(versions) == 2

    # 6. Kiểm tra dữ liệu qua Source Records API
    list_response = client.get(
        "/api/v1/source-records?limit=50&offset=0"
    )

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 2