from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from backend.app.api.routes_artifacts import router as artifacts_router
from backend.app.api.routes_health import dependency_health
from backend.app.artifacts.artifact_service import list_artifacts
from backend.app.artifacts.minio_store import minio_health
from backend.app.db.models import Artifact
from backend.app.db.postgres import get_session
from backend.app.main import create_app
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import make_session


def make_artifact(*, session_id=None) -> Artifact:
    now = datetime.now(UTC)
    return Artifact(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=session_id,
        tool_call_id=None,
        name="report.txt",
        kind="text",
        bucket="artifacts",
        object_key="sessions/report.txt",
        content_type="text/plain",
        size_bytes=128,
        checksum="abc123",
        metadata_json={"token": "secret"},
        created_at=now,
        updated_at=now,
    )


async def test_artifact_service_imports_and_lists_rows() -> None:
    row = make_artifact()
    db = FakeAsyncSession(objects=[row])

    rows = await list_artifacts(db)

    assert [item.id for item in rows] == [row.id]


def test_artifact_route_imports() -> None:
    assert artifacts_router.prefix == "/artifacts"


def test_artifact_route_lists_metadata() -> None:
    session = make_session()
    row = make_artifact(session_id=session.id)
    db = FakeAsyncSession(objects=[session, row])
    app = create_app()

    async def override_get_session():
        yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.get("/artifacts")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifacts"] == [
        {
            "id": str(row.id),
            "name": "report.txt",
            "kind": "text",
            "bucket": "artifacts",
            "object_key": "sessions/report.txt",
            "content_type": "text/plain",
            "size_bytes": 128,
            "created_at": row.created_at.isoformat(),
        }
    ]


async def test_minio_health_reports_degraded_when_unavailable(monkeypatch) -> None:
    async def fake_get(self, _url: str):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "http://minio/health"))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await minio_health()

    assert result["status"] == "degraded"
    assert "minio unavailable" in result["reason"]


async def test_dependency_health_includes_minio_degraded(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.api.routes_health.postgres_health", lambda: _ok())
    monkeypatch.setattr("backend.app.api.routes_health.redis_health", lambda: _ok())
    monkeypatch.setattr("backend.app.api.routes_health.qdrant_health", lambda: _ok())
    monkeypatch.setattr("backend.app.api.routes_health.neo4j_health", lambda: _ok())
    monkeypatch.setattr("backend.app.api.routes_health.minio_health", lambda: _degraded())
    monkeypatch.setattr("backend.app.api.routes_health.clickhouse_health", lambda: _ok())
    monkeypatch.setattr("backend.app.api.routes_health.ollama_provider.health", lambda: _ok())

    payload = await dependency_health()

    assert payload["status"] == "degraded"
    assert payload["dependencies"]["minio"]["status"] == "degraded"


async def _ok() -> dict[str, str]:
    return {"status": "ok"}


async def _degraded() -> dict[str, str]:
    return {"status": "degraded", "reason": "offline"}
