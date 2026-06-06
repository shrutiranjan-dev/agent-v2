from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.db.models import WorkerHeartbeat
from backend.app.db.postgres import get_session
from backend.app.main import create_app
from backend.app.queue.jobs import JobStatus, queue_stats
from backend.app.queue.worker_heartbeats import (
    serialize_worker_heartbeat,
    worker_heartbeat_service,
    worker_is_stale,
)
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import make_session
from backend.tests.test_queue_jobs import make_job_record, make_run


async def test_worker_heartbeat_service_tracks_totals_and_staleness(monkeypatch) -> None:
    settings = SimpleNamespace(queue=SimpleNamespace(worker_stale_after_seconds=30))
    monkeypatch.setattr("backend.app.queue.worker_heartbeats.get_settings", lambda: settings)
    db = FakeAsyncSession()

    row = await worker_heartbeat_service.upsert(
        db,
        update=SimpleNamespace(
            worker_id="worker-a",
            hostname="host-a",
            process_id=321,
            status="healthy",
            current_queue_job_id=None,
            current_run_id=None,
            claimed_jobs_delta=2,
            completed_jobs_delta=1,
            failed_jobs_delta=0,
            started_at=datetime.now(UTC) - timedelta(minutes=2),
            stopped_at=None,
            metadata={"worker": "backend-worker"},
        ),
    )
    assert row.claimed_jobs_count == 2
    assert row.completed_jobs_count == 1
    assert row.failed_jobs_count == 0

    row.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=45)
    assert worker_is_stale(row, settings=settings) is True

    serialized = serialize_worker_heartbeat(row, settings=settings, now=datetime.now(UTC))
    assert serialized["worker_id"] == "worker-a"
    assert serialized["stale"] is True
    assert serialized["claimed_jobs_count"] == 2
    assert serialized["metadata"]["worker"] == "backend-worker"


async def test_queue_retry_and_cancel_helpers_update_stats() -> None:
    session = make_session()
    run = make_run(session)
    failed_job = make_job_record(session, run, status=JobStatus.FAILED, attempt_count=2)
    failed_job.failed_at = datetime.now(UTC)
    cancelled_job = make_job_record(session, run, status=JobStatus.CANCELLED)
    scheduled_job = make_job_record(session, run, status=JobStatus.QUEUED)
    scheduled_job.available_at = datetime.now(UTC) + timedelta(seconds=30)
    db = FakeAsyncSession(objects=[session, run, failed_job, cancelled_job, scheduled_job])

    stats = await queue_stats(db)
    assert stats["failed"] == 1
    assert stats["cancelled"] == 1
    assert stats["retry_scheduled"] == 1
    assert stats["total"] == 3


def test_queue_routes_expose_jobs_stats_and_workers() -> None:
    app = create_app()
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run, status=JobStatus.FAILED)
    job.failed_at = datetime.now(UTC)
    worker = WorkerHeartbeat(
        id=uuid4(),
        worker_id="worker-a",
        hostname="host-a",
        process_id=123,
        status="healthy",
        current_queue_job_id=job.id,
        current_run_id=run.id,
        claimed_jobs_count=3,
        completed_jobs_count=2,
        failed_jobs_count=1,
        last_heartbeat_at=datetime.now(UTC),
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        metadata_json={"worker": "backend-worker"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db = FakeAsyncSession(objects=[session, run, job, worker])

    async def override_get_session():
        yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)

        jobs_response = client.get("/queue/jobs")
        assert jobs_response.status_code == 200
        assert jobs_response.json()["jobs"][0]["queue_job_id"] == str(job.id)

        stats_response = client.get("/queue/stats")
        assert stats_response.status_code == 200
        assert stats_response.json()["stats"]["failed"] == 1

        workers_response = client.get("/queue/workers")
        assert workers_response.status_code == 200
        worker_payload = workers_response.json()["workers"][0]
        assert worker_payload["worker_id"] == "worker-a"
        assert worker_payload["current_queue_job_id"] == str(job.id)

        workers_alias_response = client.get("/workers")
        assert workers_alias_response.status_code == 200
        assert workers_alias_response.json()["workers"][0]["worker_id"] == "worker-a"

        retry_response = client.post(f"/queue/jobs/{job.id}/retry", json={"reason": "operator_retry"})
        assert retry_response.status_code == 200
        assert retry_response.json()["job"]["status"] == JobStatus.QUEUED

        cancel_response = client.post(f"/queue/jobs/{job.id}/cancel", json={"reason": "operator_cancel"})
        assert cancel_response.status_code == 200
        assert cancel_response.json()["job"]["status"] == JobStatus.CANCELLED
    finally:
        app.dependency_overrides.clear()
