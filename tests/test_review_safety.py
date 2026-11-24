
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.models.access_control import (
    User,
    Role,
    UserRole,
)
from backend.models.review import (
    ReviewTask,
    ReviewDecision,
)
from backend.review.security import (
    create_access_token,
    get_password_hash,
)

from test_candidate_api import candidate_data


@pytest.fixture
def review_data(db_session, candidate_data):
    # Tao role Maker va Checker
    maker_role = Role(
        role_code="DATA_STEWARD",
        role_name="Data Steward",
    )

    checker_role = Role(
        role_code="APPROVER",
        role_name="Approver",
    )

    db_session.add_all([maker_role, checker_role])
    db_session.flush()

    # Tao hai nguoi dung doc lap
    maker = User(
        username="test_maker",
        email="maker@example.com",
        full_name="Test Maker",
        password_hash=get_password_hash("test-password"),
        status="ACTIVE",
        is_active=True,
    )

    checker = User(
        username="test_checker",
        email="checker@example.com",
        full_name="Test Checker",
        password_hash=get_password_hash("test-password"),
        status="ACTIVE",
        is_active=True,
    )

    db_session.add_all([maker, checker])
    db_session.flush()

    db_session.add_all([
        UserRole(
            user_id=maker.id,
            role_id=maker_role.id,
        ),
        UserRole(
            user_id=checker.id,
            role_id=checker_role.id,
        ),
        UserRole(
            user_id=maker.id,
            role_id=checker_role.id,
        ),
    ])

    db_session.commit()

    task = (
        db_session.query(ReviewTask)
        .filter_by(task_code="TEST-REVIEW-001")
        .one()
    )

    maker_token = create_access_token(
        user_id=maker.id,
        username=maker.username,
        roles=["DATA_STEWARD", "APPROVER"],
    )

    checker_token = create_access_token(
        user_id=checker.id,
        username=checker.username,
        roles=["APPROVER"],
    )

    return {
        "task_id": str(task.id),
        "maker_id": str(maker.id),
        "checker_id": str(checker.id),
        "maker_headers": {
            "Authorization": f"Bearer {maker_token}"
        },
        "checker_headers": {
            "Authorization": f"Bearer {checker_token}"
        },
    }


def count_rows(db_session, table):
    return db_session.execute(
        text(f"SELECT COUNT(*) FROM {table}")
    ).scalar()


def snapshot_source_data(db_session):
    tables = [
        "source_records",
        "source_record_versions",
        "canonical_entities",
        "canonical_memberships",
    ]

    return {
        table: [
            dict(row)
            for row in db_session.execute(
                text(f"SELECT * FROM {table} ORDER BY id")
            ).mappings()
        ]
        for table in tables
    }


def submit_proposal(client, review_data):
    task_id = review_data["task_id"]

    return client.post(
        f"/api/review/tasks/{task_id}/proposal",
        headers=review_data["maker_headers"],
        json={
            "task_id": task_id,
            "decision_type": "DUPLICATE",
            "decision_rationale": (
                "Matching evidence reviewed by Maker"
            ),
        },
    )


def approve_proposal(client, review_data, headers):
    task_id = review_data["task_id"]

    return client.post(
        f"/api/review/tasks/{task_id}/adjudicate",
        headers=headers,
        json={
            "task_id": task_id,
            "action": "APPROVE",
            "adjudication_notes": (
                "Matching evidence independently reviewed"
            ),
        },
    )


# 1. Review API yeu cau xac thuc
def test_review_requires_authentication(client):
    response = client.get("/api/review/queue")

    assert response.status_code == 401


# 2. Maker gui proposal thanh cong
def test_maker_submit_proposal(
    client,
    db_session,
    review_data,
):
    response = submit_proposal(client, review_data)

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["decision_type"] == "DUPLICATE"
    assert body["proposer_id"] == review_data["maker_id"]

    db_session.expire_all()

    task = db_session.query(ReviewTask).one()

    assert task.status == "IN_PROGRESS"


# 3. Maker khong duoc tu phe duyet
def test_maker_cannot_approve_own_proposal(
    client,
    db_session,
    review_data,
):
    response = submit_proposal(client, review_data)

    assert response.status_code == 200, response.text

    response = approve_proposal(
        client,
        review_data,
        review_data["maker_headers"],
    )

    assert response.status_code == 403
    assert "Self-approval" in response.json()["detail"]

    assert count_rows(
        db_session, "review_decisions"
    ) == 0


# 4. Checker doc lap phe duyet thanh cong
def test_independent_checker_approval(
    client,
    db_session,
    review_data,
):
    response = submit_proposal(client, review_data)

    assert response.status_code == 200, response.text

    response = approve_proposal(
        client,
        review_data,
        review_data["checker_headers"],
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["status"] == "APPROVED"
    assert body["proposed_by"] == review_data["maker_id"]
    assert body["approved_by"] == review_data["checker_id"]

    db_session.expire_all()

    decision = db_session.query(ReviewDecision).one()
    task = db_session.query(ReviewTask).one()

    assert decision.status == "APPROVED"
    assert task.status == "RESOLVED"


# 5. Task ID khong khop payload
@pytest.mark.parametrize(
    "endpoint",
    ["proposal", "adjudicate"],
)
def test_review_task_id_mismatch(
    client,
    review_data,
    endpoint,
):
    task_id = review_data["task_id"]

    payload = {
        "task_id": str(uuid4()),
    }

    if endpoint == "proposal":
        payload.update({
            "decision_type": "DUPLICATE",
            "decision_rationale": "Test invalid task ID",
        })
    else:
        payload.update({
            "action": "APPROVE",
        })

    response = client.post(
        f"/api/review/tasks/{task_id}/{endpoint}",
        headers=review_data["maker_headers"],
        json=payload,
    )

    assert response.status_code == 400


# 6. Proposal khong tu dong lien ket danh tinh
def test_proposal_does_not_activate_identity(
    client,
    db_session,
    review_data,
):
    before = snapshot_source_data(db_session)

    response = submit_proposal(client, review_data)

    assert response.status_code == 200, response.text

    after = snapshot_source_data(db_session)

    assert before == after

    assert count_rows(
        db_session, "canonical_entities"
    ) == 0

    assert count_rows(
        db_session, "canonical_memberships"
    ) == 0


# 7. Approval khong tu dong lien ket danh tinh
def test_approval_does_not_activate_identity(
    client,
    db_session,
    review_data,
):
    response = submit_proposal(client, review_data)

    assert response.status_code == 200, response.text

    before = snapshot_source_data(db_session)

    response = approve_proposal(
        client,
        review_data,
        review_data["checker_headers"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"

    after = snapshot_source_data(db_session)

    assert before == after

    assert count_rows(
        db_session, "canonical_entities"
    ) == 0

    assert count_rows(
        db_session, "canonical_memberships"
    ) == 0


# 8. Khong cho phe duyet lai task da resolved
def test_review_cannot_approve_twice(
    client,
    db_session,
    review_data,
):
    response = submit_proposal(client, review_data)

    assert response.status_code == 200, response.text

    response = approve_proposal(
        client,
        review_data,
        review_data["checker_headers"],
    )

    assert response.status_code == 200, response.text

    response = approve_proposal(
        client,
        review_data,
        review_data["checker_headers"],
    )

    assert response.status_code == 409

    assert count_rows(
        db_session, "review_decisions"
    ) == 1
