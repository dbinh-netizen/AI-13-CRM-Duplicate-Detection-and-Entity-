
from pathlib import Path

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = PROJECT_ROOT / "data" / "sample_csv"


def count_rows(db_session, table):
    return db_session.execute(
        text(f"SELECT COUNT(*) FROM {table}")
    ).scalar()


def test_database_matching_integration(client, db_session):
    # 1. Import du lieu mau vao Database test
    sources = [
        (
            "accounts_source_a.csv",
            "CRM_A",
            "ACCOUNT",
        ),
        (
            "accounts_source_b.csv",
            "CRM_B",
            "ACCOUNT",
        ),
        (
            "contacts_source.csv",
            "CRM_C",
            "CONTACT",
        ),
    ]

    for filename, source_code, entity_pool in sources:
        file_path = SAMPLE_DIR / filename

        assert file_path.exists(), (
            f"Missing sample file: {file_path}"
        )

        response = client.post(
            "/api/canonical/ingest",
            json={
                "file_path": str(file_path),
                "source_code": source_code,
                "entity_pool": entity_pool,
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "SUCCESS"

    # 2. Kiem tra du lieu da duoc luu vao DB
    source_count = count_rows(
        db_session, "source_records"
    )

    assert source_count == 34

    assert count_rows(
        db_session, "candidate_pairs"
    ) == 0

    runs_before = count_rows(
        db_session, "matching_runs"
    )

    # 3. Chay Matching Engine thuc te
    response = client.post(
        "/api/canonical/match-all"
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["status"] == "SUCCESS"

    report = body["report"]

    # 4. Kiem tra ca 4 Matching Run
    expected_steps = {
        "account_internal_a": 12,
        "account_internal_b": 10,
        "account_cross_ab": 22,
        "contact_internal_c": 12,
    }

    for step, expected_records in expected_steps.items():
        result = report[step]

        assert result is not None
        assert result["status"] == "COMPLETED", result

        assert result["records_scanned"] == (
            expected_records
        )

    # 5. Kiem tra ket qua Matching trong DB
    runs_after = count_rows(
        db_session, "matching_runs"
    )

    candidate_count = count_rows(
        db_session, "candidate_pairs"
    )

    evidence_count = count_rows(
        db_session, "candidate_pair_evidence"
    )

    assert runs_after - runs_before == 4
    assert candidate_count > 0
    assert evidence_count > 0

    assert report["total_candidate_pairs"] == (
        candidate_count
    )

    # 6. Kiem tra Candidate API doc ket qua Matching
    response = client.get(
        "/api/candidates?limit=200"
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["data_source"] == "DATABASE"
    assert body["total_candidates"] == candidate_count

    assert len(body["candidates"]) == candidate_count

    for pair in body["candidates"]:
        assert pair["matching_run_id"]
        assert pair["left_source_key"]
        assert pair["right_source_key"]

        assert 0 <= pair["similarity_score"] <= 100

        assert pair["decision_tier"]
        assert pair["proposed_category"]
        assert len(pair["evidence"]) > 0

        assert isinstance(pair["conflicts"], list)

    # 7. Kiem tra Matching khong tao lien ket danh tinh
    assert count_rows(
        db_session, "canonical_entities"
    ) == 0

    assert count_rows(
        db_session, "canonical_memberships"
    ) == 0

    # 8. Kiem tra so luong Source Records khong thay doi
    assert count_rows(
        db_session, "source_records"
    ) == source_count


def test_matching_processing_error(client, monkeypatch):
    from backend.canonical.matching_pipeline_service import (
        CanonicalMatchingPipelineService,
    )

    def raise_matching_error(*args, **kwargs):
        raise RuntimeError("Simulated matching failure")

    monkeypatch.setattr(
        CanonicalMatchingPipelineService,
        "execute_all_matching_steps",
        raise_matching_error,
    )

    response = client.post(
        "/api/canonical/match-all"
    )

    assert response.status_code == 500

    assert "Simulated matching failure" in (
        response.json()["detail"]
    )


import pytest

from backend.canonical.matching_pipeline_service import (
    CanonicalMatchingPipelineService,
    FullPipelineMatchingReport,
    StepMatchingSummary,
)


@pytest.mark.parametrize(
    "statuses, expected_status",
    [
        (
            ["COMPLETED"] * 4,
            "SUCCESS",
        ),
        (
            ["FAILED", "COMPLETED", "COMPLETED", "COMPLETED"],
            "FAILED",
        ),
        (
            ["COMPLETED", "HELD_CEILING_BREACH",
             "COMPLETED", "COMPLETED"],
            "HELD_CEILING_BREACH",
        ),
        (
            ["FAILED", "HELD_CEILING_BREACH",
             "COMPLETED", "COMPLETED"],
            "FAILED",
        ),
        (
            ["COMPLETED", "COMPLETED", None, "COMPLETED"],
            "FAILED",
        ),
        (
            ["UNKNOWN", "COMPLETED", "COMPLETED", "COMPLETED"],
            "FAILED",
        ),
    ],
)
def test_matching_pipeline_status(
    client,
    monkeypatch,
    statuses,
    expected_status,
):
    def build_step(index, status):
        if status is None:
            return None

        return StepMatchingSummary(
            step_name=f"Test step {index}",
            run_id=f"test-run-{index}",
            run_code=f"TEST-RUN-{index}",
            entity_pool=(
                "CONTACT" if index == 4 else "ACCOUNT"
            ),
            records_scanned=10,
            candidate_pairs_found=0,
            duration_seconds=0.1,
            status=status,
        )

    report = FullPipelineMatchingReport(
        account_internal_a=build_step(1, statuses[0]),
        account_internal_b=build_step(2, statuses[1]),
        account_cross_ab=build_step(3, statuses[2]),
        contact_internal_c=build_step(4, statuses[3]),
    )

    def mock_matching_pipeline(*args, **kwargs):
        return report

    monkeypatch.setattr(
        CanonicalMatchingPipelineService,
        "execute_all_matching_steps",
        mock_matching_pipeline,
    )

    response = client.post("/api/canonical/match-all")

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["status"] == expected_status
    assert "report" in body

