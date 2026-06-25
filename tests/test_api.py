from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATA_DIR", "artifacts")
os.environ.pop("RAILWAY_ENVIRONMENT", None)
os.environ.pop("RAILWAY_PROJECT_ID", None)

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_job_path_traversal_returns_404(client: TestClient) -> None:
    os.environ["PIPELINE_API_KEY"] = "test-pipeline-key"
    response = client.get(
        "/api/pipeline/jobs/../knowledge-sync-state",
        headers={"X-Pipeline-Key": "test-pipeline-key"},
    )
    assert response.status_code == 404


def test_openapi_available_locally(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
