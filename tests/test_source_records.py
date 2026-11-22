from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_source_record_invalid_uuid():
    response = client.get(
        "/api/v1/source-records/not-a-valid-uuid"
    )

    assert response.status_code == 422

    body = response.json()

    assert "detail" in body
    assert body["detail"][0]["loc"] == ["path", "record_id"]


def test_source_records_invalid_limit():
    response = client.get(
        "/api/v1/source-records?limit=0"
    )

    assert response.status_code == 422


def test_source_records_invalid_offset():
    response = client.get(
        "/api/v1/source-records?offset=-1"
    )

    assert response.status_code == 422

def test_source_records_empty_database(client):
    response = client.get(
        "/api/v1/source-records?limit=50&offset=0"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 0
    assert body["records"] == []
    assert body["limit"] == 50
    assert body["offset"] == 0

def test_source_record_not_found(client):
    record_id = "00000000-0000-4000-8000-000000000001"

    response = client.get(
        f"/api/v1/source-records/{record_id}"
    )

    assert response.status_code == 404

    body = response.json()

    assert body["detail"]["code"] == "SOURCE_RECORD_NOT_FOUND"
    assert body["detail"]["message"] == "Source record not found"

from uuid import uuid4

from backend.models.intake import (
    SourceSystem,
    ImportBatch,
    SourceRecord,
)


def test_source_record_detail_success(client, db_session):
    source_system_id = uuid4()
    batch_id = uuid4()
    record_id = uuid4()

    # 1. Tạo hệ thống nguồn trong DB test
    source_system = SourceSystem(
        id=source_system_id,
        source_code="TEST_CRM",
        source_name="Test CRM",
        system_type="CRM",
        entity_type="ACCOUNT",
        is_active=True,
    )

    db_session.add(source_system)
    db_session.flush()

    # 2. Tạo import batch
    batch = ImportBatch(
        id=batch_id,
        batch_code=f"TEST-{uuid4().hex[:8]}",
        source_system_id=source_system_id,
        batch_type="FULL",
        file_name="test_accounts.csv",
        file_checksum=uuid4().hex,
        file_size_bytes=100,
        status="COMPLETED",
    )

    db_session.add(batch)
    db_session.flush()

    # 3. Tạo SourceRecord
    record = SourceRecord(
        id=record_id,
        source_system_id=source_system_id,
        entity_type="ACCOUNT",
        source_key="ACC-TEST-001",
        import_batch_id=batch_id,
        entity_subtype="COMPANY",
        status="ACTIVE",
        record_payload={
            "source_key": "ACC-TEST-001",
            "legal_name": "Test Company",
        },
    )

    db_session.add(record)
    db_session.commit()

    # 4. Gọi API
    response = client.get(
        f"/api/v1/source-records/{record_id}"
    )

    # 5. Kiểm tra response
    assert response.status_code == 200

    body = response.json()

    assert body["record"]["id"] == str(record_id)
    assert body["record"]["source_key"] == "ACC-TEST-001"
    assert body["record"]["entity_type"] == "ACCOUNT"
    assert body["record"]["record_payload"]["legal_name"] == "Test Company"

    assert body["source_system"]["source_code"] == "TEST_CRM"
    assert body["import_batch"]["status"] == "COMPLETED"

    # Chưa tạo SourceRecordVersion hoặc NormalizedFeature
    assert body["version"] is None
    assert body["normalized_fields"] == []