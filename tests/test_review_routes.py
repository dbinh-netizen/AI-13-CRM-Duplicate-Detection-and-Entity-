
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_review_routes_have_correct_prefix():
    """Kiểm tra các endpoint Review có đúng prefix."""

    response = client.get("/openapi.json")

    assert response.status_code == 200

    paths = response.json()["paths"]

    expected_routes = {
        "/api/review/queue": ["get"],
        "/api/review/tasks/{task_id}/assign": ["post"],
        "/api/review/tasks/{task_id}/release": ["post"],
        "/api/review/tasks/{task_id}/proposal": ["get", "post"],
        "/api/review/tasks/{task_id}/adjudicate": ["post"],
        "/api/review/clusters/{cluster_id}": ["get"],
        "/api/review/clusters/{cluster_id}/split": ["post"],
        "/api/review/pairs/unlink": ["post"],
        "/api/review/conflicts": ["get"],
    }

    for path, methods in expected_routes.items():
        assert path in paths, f"Missing route: {path}"

        for method in methods:
            assert method in paths[path], (
                f"Missing method: {method.upper()} {path}"
            )


def test_review_routes_have_no_duplicate_prefix():
    """Đảm bảo không còn route /api/api/review."""

    response = client.get("/openapi.json")

    assert response.status_code == 200

    paths = response.json()["paths"]

    duplicate_routes = [
        path
        for path in paths
        if path.startswith("/api/api/review")
    ]

    assert not duplicate_routes, (
        f"Duplicate review routes: {duplicate_routes}"
    )
