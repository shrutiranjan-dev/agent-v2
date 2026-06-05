from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.app.core.config import Settings
from backend.app.db.models import AgentRun, PermissionRequest, QueueJobRecord, Session, ToolCall
from backend.app.queue.jobs import (
    JobStatus,
    JobType,
    QueueJob,
    RuntimeQueue,
    execute_job,
    mark_job_failed,
)
from backend.app.runtime.loop_guard import input_hash
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import FakeProvider, make_session, make_user_message


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.closed = False

    async def rpush(self, name: str, value: str) -> None:
        self.lists.setdefault(name, []).append(value)

    async def blpop(self, name: str, timeout: int = 0):
        _ = timeout
        values = self.lists.get(name, [])
        if not values:
            return None
        return name, values.pop(0)

    async def aclose(self) -> None:
        self.closed = True


class FailingRedis(FakeRedis):
    async def rpush(self, name: str, value: str) -> None:
        _ = name, value
        raise RedisConnectionError("redis unavailable")

    async def blpop(self, name: str, timeout: int = 0):
        _ = name, timeout
        raise RedisConnectionError("redis unavailable")


def queue_settings(*, enabled: bool = True):
    return SimpleNamespace(
        queue=SimpleNamespace(
            enabled=enabled,
            name="test:jobs",
            dead_letter_name="test:jobs:dead",
            poll_timeout_seconds=1,
            max_attempts=2,
            retry_backoff_seconds=0,
            visibility_timeout_seconds=10,
            worker_id=None,
        )
    )


def make_run(session: Session, *, status: str = "queued") -> AgentRun:
    now = datetime.now(UTC)
    return AgentRun(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_id=session.agent_id,
        model_provider=session.model_provider,
        model_name=session.model_name,
        status=status,
        step_count=0,
        started_at=now,
        created_at=now,
        updated_at=now,
    )


def make_job_record(session: Session, run: AgentRun, *, status: str = "queued", attempt_count: int = 0) -> QueueJobRecord:
    now = datetime.now(UTC)
    return QueueJobRecord(
        id=uuid4(),
        job_type=JobType.AGENT_RUN,
        status=status,
        run_id=run.id,
        session_id=session.id,
        payload={
            "agent_run_id": str(run.id),
            "session_id": str(session.id),
            "user_id": str(session.created_by_user_id),
        },
        idempotency_key=f"agent_run:{session.id}:{uuid4()}:{session.agent_id}",
        attempt_count=attempt_count,
        max_attempts=2,
        available_at=now,
        created_at=now,
        updated_at=now,
    )


async def test_enqueue_agent_run_creates_durable_row_and_redis_signal() -> None:
    fake = FakeRedis()
    queue = RuntimeQueue(settings=queue_settings(), redis_factory=lambda: fake)
    session = make_session()
    run = make_run(session)
    message = make_user_message(session)
    db = FakeAsyncSession(objects=[session, run, message])

    job = await queue.enqueue_agent_run(
        db,
        agent_run_id=run.id,
        session_id=session.id,
        user_message_id=message.id,
        user_id=session.created_by_user_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        agent_id=session.agent_id,
    )

    assert job.job_type == JobType.AGENT_RUN
    assert job.status == JobStatus.QUEUED
    assert job.run_id == run.id
    assert fake.lists["test:jobs"]
    message_payload = QueueJob.model_validate_json(fake.lists["test:jobs"][0])
    assert message_payload.queue_job_id == str(job.id)
    assert "agent_run_id" not in message_payload.model_dump()
    assert fake.closed is True


async def test_duplicate_agent_enqueue_returns_same_queue_job() -> None:
    fake = FakeRedis()
    queue = RuntimeQueue(settings=queue_settings(), redis_factory=lambda: fake)
    session = make_session()
    run = make_run(session)
    message = make_user_message(session)
    db = FakeAsyncSession(objects=[session, run, message])

    first = await queue.enqueue_agent_run(
        db,
        agent_run_id=run.id,
        session_id=session.id,
        user_message_id=message.id,
        user_id=None,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        agent_id=session.agent_id,
    )
    second = await queue.enqueue_agent_run(
        db,
        agent_run_id=run.id,
        session_id=session.id,
        user_message_id=message.id,
        user_id=None,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        agent_id=session.agent_id,
    )

    assert second.id == first.id


async def test_duplicate_permission_resume_enqueue_returns_same_queue_job() -> None:
    fake = FakeRedis()
    queue = RuntimeQueue(settings=queue_settings(), redis_factory=lambda: fake)
    session = make_session()
    run = make_run(session)
    request_id = uuid4()
    db = FakeAsyncSession(objects=[session, run])

    first = await queue.enqueue_permission_resume(
        db,
        permission_request_id=request_id,
        agent_run_id=run.id,
        session_id=session.id,
        user_id=None,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
    )
    second = await queue.enqueue_permission_resume(
        db,
        permission_request_id=request_id,
        agent_run_id=run.id,
        session_id=session.id,
        user_id=None,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
    )

    assert second.id == first.id
    assert first.job_type == JobType.PERMISSION_RESUME


async def test_two_workers_cannot_claim_same_queue_job() -> None:
    queue = RuntimeQueue(settings=queue_settings())
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run)
    db = FakeAsyncSession(objects=[session, run, job])

    first = await queue.claim_job(db, queue_job_id=job.id, worker_id="worker-a")
    second = await queue.claim_job(db, queue_job_id=job.id, worker_id="worker-b")

    assert first is job
    assert second is None
    assert job.status == JobStatus.CLAIMED
    assert job.claimed_by == "worker-a"


async def test_stale_job_can_be_reclaimed() -> None:
    queue = RuntimeQueue(settings=queue_settings())
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run, status="running")
    job.claimed_by = "old-worker"
    job.claimed_at = datetime.now(UTC) - timedelta(seconds=60)
    db = FakeAsyncSession(objects=[session, run, job])

    claimed = await queue.claim_job(db, queue_job_id=job.id, worker_id="new-worker")

    assert claimed is job
    assert job.status == JobStatus.CLAIMED
    assert job.claimed_by == "new-worker"


async def test_completed_job_is_not_rerun_on_duplicate_redis_message(monkeypatch) -> None:
    queue = RuntimeQueue(settings=queue_settings())
    session = make_session()
    run = make_run(session, status="completed")
    job = make_job_record(session, run, status="completed")
    db = FakeAsyncSession(objects=[session, run, job])

    claimed = await queue.claim_job(db, queue_job_id=job.id, worker_id="worker-a")

    assert claimed is None
    assert job.status == JobStatus.COMPLETED


async def test_max_attempts_moves_job_to_dead_letter() -> None:
    queue = RuntimeQueue(settings=queue_settings())
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run, status="running", attempt_count=2)
    db = FakeAsyncSession(objects=[session, run, job])

    requeued = await queue.fail_job(db, job, worker_id="worker-a", error="boom")

    assert requeued is False
    assert job.status == JobStatus.DEAD_LETTER
    assert job.last_error == "boom"


async def test_failed_job_schedules_retry_and_records_last_error() -> None:
    queue = RuntimeQueue(settings=queue_settings())
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run, status="running", attempt_count=1)
    db = FakeAsyncSession(objects=[session, run, job])

    requeued = await queue.fail_job(db, job, worker_id="worker-a", error="temporary")

    assert requeued is True
    assert job.status == JobStatus.QUEUED
    assert job.last_error == "temporary"
    assert job.available_at >= datetime.now(UTC) - timedelta(seconds=1)


async def test_queue_falls_back_to_local_buffer_when_redis_unavailable() -> None:
    queue = RuntimeQueue(settings=queue_settings(), redis_factory=FailingRedis)
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run)

    await queue.publish_job(job)
    dequeued = await queue.dequeue()

    assert dequeued is not None
    assert dequeued.queue_job_id == str(job.id)


async def test_worker_executes_queued_agent_run(monkeypatch) -> None:
    session = make_session()
    run = make_run(session)
    message = make_user_message(session)
    job = make_job_record(session, run)
    db = FakeAsyncSession(messages=[message], objects=[session, run, job])
    provider = FakeProvider(['{"type":"final","content":"queued done"}'])
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)

    await execute_job(db, job)

    assert run.status == "completed"
    assert session.status == "idle"


async def test_worker_executes_queued_permission_resume(monkeypatch, tmp_path) -> None:
    session = make_session(agent_id="build")
    run = make_run(session, status="resume_queued")
    tool_input = {"path": "approved.txt", "content": "ok"}
    digest = input_hash(tool_input)
    call = ToolCall(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=run.id,
        agent_id="build",
        tool_name="write.file",
        input_json=tool_input,
        input_hash=digest,
        status="waiting_permission",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    request = PermissionRequest(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=run.id,
        tool_call_id=call.id,
        permission_key="write.file",
        resource=str(tmp_path / "approved.txt"),
        action="ask",
        status="approved",
        input_json=tool_input,
        metadata_json={"tool": "write.file", "input_hash": digest},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    call.permission_request_id = request.id
    job = QueueJobRecord(
        id=uuid4(),
        job_type=JobType.PERMISSION_RESUME,
        status=JobStatus.RUNNING,
        run_id=run.id,
        session_id=session.id,
        permission_request_id=request.id,
        payload={
            "permission_request_id": str(request.id),
            "agent_run_id": str(run.id),
            "session_id": str(session.id),
            "user_id": str(session.created_by_user_id),
        },
        idempotency_key=f"permission_resume:{request.id}",
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db = FakeAsyncSession(messages=[make_user_message(session)], objects=[session, run, call, request, job])
    provider = FakeProvider(['{"type":"final","content":"resume done"}'])
    fake_settings = SimpleNamespace(workspace_root=tmp_path, runtime=SimpleNamespace(max_tool_repeats=3))
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: fake_settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: fake_settings)

    await execute_job(db, job)

    assert run.status == "completed"
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "ok"


async def test_failed_final_job_marks_run_failed() -> None:
    session = make_session()
    run = make_run(session)
    job = make_job_record(session, run)
    db = FakeAsyncSession(objects=[session, run, job])

    await mark_job_failed(db, job, error="boom", final=True)

    assert run.status == "failed"
    assert session.status == "failed"
    assert run.error == "boom"


def test_queue_disabled_dev_mode_is_allowed(monkeypatch) -> None:
    monkeypatch.delenv("AP_QUEUE_ENABLED", raising=False)
    monkeypatch.setenv("AP_ENV", "development")

    settings = Settings(_env_file=None)

    assert settings.queue.enabled is False


def test_production_with_queue_disabled_fails(monkeypatch) -> None:
    monkeypatch.setenv("AP_ENV", "production")
    monkeypatch.setenv("AP_SECURITY_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("AP_DATABASE_URL", "postgresql+asyncpg://prod:secret@db:5432/app")
    monkeypatch.setenv("AP_MINIO_SECRET_KEY", "not-minioadmin")
    monkeypatch.setenv("AP_NEO4J_PASSWORD", "not-agent-platform")
    monkeypatch.setenv("AP_QUEUE_ENABLED", "false")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert "queue.enabled must be true in production" in str(exc.value)
