
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from main import app
from backend.models import MatchingRun
from backend.models.intake import (
    SourceSystem,
    ImportBatch,
    SourceRecord,
)
from backend.models.matching import (
    CandidatePair,
    CandidatePairEvidence,
)
from backend.models.review import ReviewTask


@pytest.fixture
def candidate_data(db_session):
    pairs = {}

    for entity_type in ["ACCOUNT", "CONTACT"]:
        source = SourceSystem(
            source_code=f"TEST_{entity_type}",
            source_name=f"Test {entity_type}",
            system_type="CRM",
            entity_type=entity_type,
            is_active=True,
        )

        db_session.add(source)
        db_session.flush()

        batch = ImportBatch(
            batch_code=f"TEST-{uuid4().hex[:8]}",
            source_system_id=source.id,
            batch_type="FULL",
            file_name="test.csv",
            file_checksum=uuid4().hex,
            file_size_bytes=100,
            status="COMPLETED",
        )

        db_session.add(batch)
        db_session.flush()

        record_ids = sorted([uuid4(), uuid4()])

        for index, record_id in enumerate(record_ids):
            record = SourceRecord(
                id=record_id,
                source_system_id=source.id,
                import_batch_id=batch.id,
                source_key=f"{entity_type}-{index + 1}",
                entity_type=entity_type,
                status="ACTIVE",
                record_payload={
                    "legal_name": "Test Company"
                },
            )

            db_session.add(record)

        run = MatchingRun(
            run_code=f"RUN-{entity_type}",
            entity_pool=entity_type,
            status="COMPLETED",
            total_candidates=1,
        )

        db_session.add(run)
        db_session.flush()

        pair = CandidatePair(
            matching_run_id=run.id,
            left_source_record_id=record_ids[0],
            right_source_record_id=record_ids[1],
            entity_type=entity_type,
            total_score=95.0 if entity_type == "ACCOUNT" else 70.0,
            decision_tier=(
                "HIGH_CONFIDENCE"
                if entity_type == "ACCOUNT"
                else "SUSPECTED"
            ),
            proposed_category=(
                "MERGE_CANDIDATE"
                if entity_type == "ACCOUNT"
                else "REVIEW"
            ),
        )

        db_session.add(pair)
        db_session.flush()

        evidence = CandidatePairEvidence(
            candidate_pair_id=pair.id,
            rule_name="RULE_PHONE",
            field_name="phone",
            similarity_score=100.0,
            evidence_direction="POSITIVE",
            evidence_weight=0.15,
            policy_version="1.0-EXPERIMENTAL",
        )

        db_session.add(evidence)

        if entity_type == "ACCOUNT":
            conflict = CandidatePairEvidence(
                candidate_pair_id=pair.id,
                rule_name="RULE_CONFLICT_DETECTION",
                field_name="brand_match_legal_variance",
                similarity_score=0.0,
                evidence_direction="NEGATIVE",
                evidence_weight=0.0,
            )

            task = ReviewTask(
                task_code="TEST-REVIEW-001",
                task_type="PAIR",
                candidate_pair_id=pair.id,
                status="OPEN",
                priority="MEDIUM",
            )

            db_session.add_all([conflict, task])

        pairs[entity_type] = {
            "id": str(pair.id),
            "matching_run_id": str(run.id),
        }

    db_session.commit()

    return pairs


# 1. Kiem tra API doc du lieu tu Database
def test_candidates_from_database(client, candidate_data):
    response = client.get("/api/candidates")

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["data_source"] == "DATABASE"
    assert body["total_candidates"] == 2
    assert len(body["candidates"]) == 2


# 2. Kiem tra score va evidence
def test_candidate_score_and_evidence(client, candidate_data):
    response = client.get(
        "/api/candidates?entity_type=ACCOUNT"
    )

    assert response.status_code == 200

    pair = response.json()["candidates"][0]

    assert pair["id"] == candidate_data["ACCOUNT"]["id"]
    assert pair["similarity_score"] == 95.0
    assert pair["decision_tier"] == "HIGH_CONFIDENCE"
    assert pair["proposed_category"] == "MERGE_CANDIDATE"

    assert any(
        item["rule_name"] == "RULE_PHONE"
        and item["similarity_score"] == 100.0
        for item in pair["evidence"]
    )


# 3. Kiem tra conflicts
def test_candidate_conflicts(client, candidate_data):
    response = client.get(
        "/api/candidates?entity_type=ACCOUNT"
    )

    assert response.status_code == 200

    conflicts = response.json()["candidates"][0]["conflicts"]

    assert len(conflicts) == 1
    assert conflicts[0]["rule_name"] == "RULE_CONFLICT_DETECTION"
    assert conflicts[0]["evidence_direction"] == "NEGATIVE"


# 4. Kiem tra review state
def test_candidate_review_state(client, candidate_data):
    response = client.get(
        "/api/candidates?entity_type=ACCOUNT"
    )

    assert response.status_code == 200

    pair = response.json()["candidates"][0]

    assert pair["review_state"] == "OPEN"
    assert len(pair["review_tasks"]) == 1
    assert pair["review_tasks"][0]["status"] == "OPEN"


# 5. Kiem tra candidate chua co review task
def test_candidate_without_review_task(client, candidate_data):
    response = client.get(
        "/api/candidates?entity_type=CONTACT"
    )

    assert response.status_code == 200

    pair = response.json()["candidates"][0]

    assert pair["review_state"] is None
    assert pair["review_tasks"] == []


# 6. Kiem tra filter entity type
@pytest.mark.parametrize(
    "entity_type",
    ["ACCOUNT", "CONTACT"],
)
def test_candidate_entity_filter(
    client,
    candidate_data,
    entity_type,
):
    response = client.get(
        f"/api/candidates?entity_type={entity_type}"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["total_candidates"] == 1
    assert body["candidates"][0]["entity_pool"] == entity_type


# 7. Kiem tra filter matching run
def test_candidate_matching_run_filter(client, candidate_data):
    run_id = candidate_data["ACCOUNT"]["matching_run_id"]

    response = client.get(
        f"/api/candidates?matching_run_id={run_id}"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["total_candidates"] == 1
    assert body["candidates"][0]["matching_run_id"] == run_id


# 8. Kiem tra pagination
def test_candidate_pagination(client, candidate_data):
    first = client.get("/api/candidates?limit=1&offset=0")
    second = client.get("/api/candidates?limit=1&offset=1")

    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()

    assert first_body["total_candidates"] == 2
    assert second_body["total_candidates"] == 2

    assert len(first_body["candidates"]) == 1
    assert len(second_body["candidates"]) == 1

    assert first_body["candidates"][0]["id"] != (
        second_body["candidates"][0]["id"]
    )


# 9. Kiem tra validation
@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=201",
        "offset=-1",
        "entity_type=INVALID",
        "matching_run_id=abc",
    ],
)
def test_candidate_invalid_input(client, query):
    response = client.get(f"/api/candidates?{query}")

    assert response.status_code == 422


# 10. Kiem tra Database rong
def test_candidate_empty_database(client):
    response = client.get("/api/candidates")

    assert response.status_code == 200

    body = response.json()

    assert body["total_candidates"] == 0
    assert body["candidates"] == []


# 11. Kiem tra loi truy van Database
def test_candidate_database_error(
    client,
    db_session,
    monkeypatch,
):
    def raise_database_error(*args, **kwargs):
        raise SQLAlchemyError("Simulated database error")

    monkeypatch.setattr(
        db_session,
        "query",
        raise_database_error,
    )

    with TestClient(
        app,
        raise_server_exceptions=False,
    ) as error_client:
        response = error_client.get("/api/candidates")

    assert response.status_code == 500


# 12. Kiem tra GET API khong tao lien ket danh tinh
def test_candidate_api_read_only(
    client,
    db_session,
    candidate_data,
):
    tables = [
        "source_records",
        "matching_runs",
        "candidate_pairs",
        "candidate_pair_evidence",
        "review_tasks",
        "review_decisions",
        "canonical_entities",
        "canonical_memberships",
    ]

    def get_counts():
        return {
            table: db_session.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()
            for table in tables
        }

    before = get_counts()

    response = client.get("/api/candidates")

    assert response.status_code == 200

    after = get_counts()

    assert before == after
    assert after["canonical_entities"] == 0
    assert after["canonical_memberships"] == 0

def test_candidate_nullable_evidence_direction(
    client,
    db_session,
    candidate_data,
):
    evidence = (
        db_session.query(CandidatePairEvidence)
        .filter_by(rule_name="RULE_PHONE")
        .first()
    )

    evidence_id = str(evidence.id)

    evidence.evidence_direction = None
    db_session.commit()

    response = client.get("/api/candidates")

    assert response.status_code == 200, response.text

    items = [
        item
        for pair in response.json()["candidates"]
        for item in pair["evidence"]
        if item["id"] == evidence_id
    ]

    assert len(items) == 1
    assert items[0]["evidence_direction"] is None