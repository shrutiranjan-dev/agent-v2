import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings, get_settings
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_text
from backend.app.db.models import AgentRun, QueueJobRecord, Session
from backend.app.queue.redis_client import get_redis
from backend.app.runtime.event_bus import event_bus


class QueueDisabledError(RuntimeError):
    pass


class JobClaimError(RuntimeError):
    pass


class JobType(StrEnum):
    AGENT_RUN = "agent_run"
    PERMISSION_RESUME = "permission_resume"
    HUMAN_INPUT_RESUME = "human_input_resume"
    SESSION_COMPACTION = "session_compaction"


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class QueueJob(BaseModel):
    queue_job_id: str


class RuntimeQueue:
    def __init__(self, *, settings: Settings | None = None, redis_factory=get_redis) -> None:
        self._settings = settings
        self._redis_factory = redis_factory

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.queue.enabled

    async def enqueue_agent_run(
        self,
        db: AsyncSession,
        *,
        agent_run_id: UUID,
        session_id: UUID,
        user_message_id: UUID,
        user_id: UUID | None,
        organization_id: UUID,
        project_id: UUID,
        workspace_id: UUID,
        agent_id: str,
        publish: bool = True,
    ) -> QueueJobRecord:
        key = self.agent_run_idempotency_key(session_id=session_id, user_message_id=user_message_id, agent_id=agent_id)
        payload = {
            "agent_run_id": str(agent_run_id),
            "session_id": str(session_id),
            "user_message_id": str(user_message_id),
            "user_id": str(user_id) if user_id else None,
            "organization_id": str(organization_id),
            "project_id": str(project_id),
            "workspace_id": str(workspace_id),
            "agent_id": agent_id,
        }
        job = await self._get_or_create_job(
            db,
            job_type=JobType.AGENT_RUN,
            idempotency_key=key,
            payload=payload,
            run_id=agent_run_id,
            session_id=session_id,
            user_message_id=user_message_id,
        )
        if publish:
            await self.publish_job(job)
        return job

    async def enqueue_permission_resume(
        self,
        db: AsyncSession,
        *,
        permission_request_id: UUID,
        agent_run_id: UUID,
        session_id: UUID,
        user_id: UUID | None,
        organization_id: UUID,
        project_id: UUID,
        workspace_id: UUID,
        publish: bool = True,
    ) -> QueueJobRecord:
        key = self.permission_resume_idempotency_key(permission_request_id)
        payload = {
            "permission_request_id": str(permission_request_id),
            "agent_run_id": str(agent_run_id),
            "session_id": str(session_id),
            "user_id": str(user_id) if user_id else None,
            "organization_id": str(organization_id),
            "project_id": str(project_id),
            "workspace_id": str(workspace_id),
        }
        job = await self._get_or_create_job(
            db,
            job_type=JobType.PERMISSION_RESUME,
            idempotency_key=key,
            payload=payload,
            run_id=agent_run_id,
            session_id=session_id,
            permission_request_id=permission_request_id,
        )
        if publish:
            await self.publish_job(job)
        return job

    async def enqueue_human_input_resume(
        self,
        db: AsyncSession,
        *,
        human_input_request_id: UUID,
        agent_run_id: UUID,
        session_id: UUID,
        user_id: UUID | None,
        organization_id: UUID,
        project_id: UUID,
        workspace_id: UUID,
        publish: bool = True,
    ) -> QueueJobRecord:
        key = self.human_input_resume_idempotency_key(human_input_request_id)
        payload = {
            "human_input_request_id": str(human_input_request_id),
            "agent_run_id": str(agent_run_id),
            "session_id": str(session_id),
            "user_id": str(user_id) if user_id else None,
            "organization_id": str(organization_id),
            "project_id": str(project_id),
            "workspace_id": str(workspace_id),
        }
        job = await self._get_or_create_job(
            db,
            job_type=JobType.HUMAN_INPUT_RESUME,
            idempotency_key=key,
            payload=payload,
            run_id=agent_run_id,
            session_id=session_id,
            human_input_request_id=human_input_request_id,
        )
        if publish:
            await self.publish_job(job)
        return job

    async def enqueue_session_compaction(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        source_message_end_id: UUID | None,
        user_id: UUID | None,
        organization_id: UUID,
        project_id: UUID,
        workspace_id: UUID,
        reason: str,
        publish: bool = True,
    ) -> QueueJobRecord:
        key = self.session_compaction_idempotency_key(
            session_id=session_id,
            source_message_end_id=source_message_end_id,
        )
        payload = {
            "session_id": str(session_id),
            "source_message_end_id": str(source_message_end_id) if source_message_end_id else None,
            "user_id": str(user_id) if user_id else None,
            "organization_id": str(organization_id),
            "project_id": str(project_id),
            "workspace_id": str(workspace_id),
            "reason": reason,
        }
        job = await self._get_or_create_job(
            db,
            job_type=JobType.SESSION_COMPACTION,
            idempotency_key=key,
            payload=payload,
            session_id=session_id,
        )
        if publish:
            await self.publish_job(job)
        return job

    async def publish_job(self, job: QueueJobRecord) -> None:
        if not self.enabled:
            raise QueueDisabledError("Queue is disabled.")
        client = self._redis_factory()
        try:
            await client.rpush(self.settings.queue.name, QueueJob(queue_job_id=str(job.id)).model_dump_json())
        finally:
            close = getattr(client, "aclose", None)
            if close:
                await close()

    async def dequeue(self) -> QueueJob | None:
        if not self.enabled:
            raise QueueDisabledError("Queue is disabled.")
        client = self._redis_factory()
        try:
            try:
                item = await client.blpop(self.settings.queue.name, timeout=self.settings.queue.poll_timeout_seconds)
            except RedisTimeoutError:
                item = None
        finally:
            close = getattr(client, "aclose", None)
            if close:
                await close()
        if not item:
            return None
        _queue_name, raw = item
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return QueueJob.model_validate_json(raw)

    async def claim_job(self, db: AsyncSession, *, queue_job_id: UUID, worker_id: str) -> QueueJobRecord | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self.settings.queue.visibility_timeout_seconds)
        row = await self._get_job_for_update(db, queue_job_id)
        if row is None:
            return None
        if row.status in {JobStatus.COMPLETED, JobStatus.DEAD_LETTER, JobStatus.CANCELLED}:
            return None
        if row.status in {JobStatus.CLAIMED, JobStatus.RUNNING}:
            if not row.claimed_at or row.claimed_at > stale_before:
                return None
        if row.available_at and row.available_at > now:
            await self.publish_job(row)
            return None
        row.status = JobStatus.CLAIMED
        row.claimed_by = worker_id
        row.claimed_at = now
        row.updated_at = now
        await db.flush()
        await self._publish_queue_event(db, row, EventType.QUEUE_JOB_CLAIMED, payload={"worker_id": worker_id})
        return row

    async def start_claimed_job(self, db: AsyncSession, job: QueueJobRecord, *, worker_id: str) -> None:
        if job.status != JobStatus.CLAIMED or job.claimed_by != worker_id:
            raise JobClaimError(f"Queue job {job.id} is not claimed by worker {worker_id}.")
        job.status = JobStatus.RUNNING
        job.attempt_count += 1
        job.updated_at = datetime.now(UTC)
        await db.flush()
        await self._publish_queue_event(db, job, EventType.QUEUE_JOB_STARTED, payload={"worker_id": worker_id})

    async def complete_job(self, db: AsyncSession, job: QueueJobRecord, *, worker_id: str) -> None:
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.updated_at = job.completed_at
        job.claimed_by = worker_id
        await db.flush()
        await self._publish_queue_event(db, job, EventType.QUEUE_JOB_COMPLETED, payload={"worker_id": worker_id})

    async def fail_job(
        self,
        db: AsyncSession,
        job: QueueJobRecord,
        *,
        worker_id: str,
        error: str,
    ) -> bool:
        safe_error = redact_text(error)
        now = datetime.now(UTC)
        job.last_error = safe_error
        job.failed_at = now
        job.updated_at = now
        job.claimed_by = worker_id
        await self._publish_queue_event(
            db,
            job,
            EventType.QUEUE_JOB_FAILED,
            severity="error",
            payload={"worker_id": worker_id, "error": safe_error},
        )
        if job.attempt_count >= job.max_attempts:
            job.status = JobStatus.DEAD_LETTER
            await db.flush()
            await self._publish_queue_event(
                db,
                job,
                EventType.QUEUE_JOB_DEAD_LETTERED,
                severity="error",
                payload={"worker_id": worker_id, "error": safe_error},
            )
            return False

        job.status = JobStatus.QUEUED
        job.claimed_at = None
        delay = self.settings.queue.retry_backoff_seconds
        job.available_at = now + timedelta(seconds=delay)
        await db.flush()
        await self._publish_queue_event(
            db,
            job,
            EventType.QUEUE_JOB_RETRY_SCHEDULED,
            severity="warning",
            payload={
                "worker_id": worker_id,
                "error": safe_error,
                "available_at": job.available_at.isoformat(),
            },
        )
        return True

    async def retry_or_dead_letter(self, job: QueueJob, *, error: str) -> bool:
        _ = error
        raise RuntimeError("retry_or_dead_letter requires a database session in the durable queue implementation.")

    def agent_run_idempotency_key(self, *, session_id: UUID, user_message_id: UUID, agent_id: str) -> str:
        return f"agent_run:{session_id}:{user_message_id}:{agent_id}"

    def permission_resume_idempotency_key(self, permission_request_id: UUID) -> str:
        return f"permission_resume:{permission_request_id}"

    def human_input_resume_idempotency_key(self, human_input_request_id: UUID) -> str:
        return f"human_input_resume:{human_input_request_id}"

    def session_compaction_idempotency_key(self, *, session_id: UUID, source_message_end_id: UUID | None) -> str:
        return f"session_compaction:{session_id}:{source_message_end_id or 'latest'}"

    async def _get_or_create_job(
        self,
        db: AsyncSession,
        *,
        job_type: JobType,
        idempotency_key: str,
        payload: dict[str, Any],
        run_id: UUID | None = None,
        session_id: UUID | None = None,
        permission_request_id: UUID | None = None,
        human_input_request_id: UUID | None = None,
        user_message_id: UUID | None = None,
    ) -> QueueJobRecord:
        existing = await _find_job_by_idempotency_key(db, idempotency_key)
        if existing:
            return existing

        now = datetime.now(UTC)
        if not hasattr(db, "objects"):
            stmt = (
                insert(QueueJobRecord)
                .values(
                    job_type=str(job_type),
                    status=str(JobStatus.QUEUED),
                    run_id=run_id,
                    session_id=session_id,
                    permission_request_id=permission_request_id,
                    human_input_request_id=human_input_request_id,
                    user_message_id=user_message_id,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    max_attempts=self.settings.queue.max_attempts,
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                .returning(QueueJobRecord.id)
            )
            result = await db.execute(stmt)
            inserted_id = result.scalar_one_or_none()
            job = await db.get(QueueJobRecord, inserted_id) if inserted_id else await _find_job_by_idempotency_key(db, idempotency_key)
            if not job:
                raise RuntimeError(f"Unable to create or load queue job for idempotency key {idempotency_key}")
            if inserted_id:
                await self._publish_queue_event(db, job, EventType.QUEUE_JOB_CREATED)
            return job

        job = QueueJobRecord(
            job_type=str(job_type),
            status=str(JobStatus.QUEUED),
            run_id=run_id,
            session_id=session_id,
            permission_request_id=permission_request_id,
            human_input_request_id=human_input_request_id,
            user_message_id=user_message_id,
            payload=payload,
            idempotency_key=idempotency_key,
            max_attempts=self.settings.queue.max_attempts,
            available_at=now,
        )
        db.add(job)
        await db.flush()
        await self._publish_queue_event(db, job, EventType.QUEUE_JOB_CREATED)
        return job

    async def _get_job_for_update(self, db: AsyncSession, queue_job_id: UUID) -> QueueJobRecord | None:
        if hasattr(db, "objects"):
            return await db.get(QueueJobRecord, queue_job_id)
        return await db.scalar(
            select(QueueJobRecord).where(QueueJobRecord.id == queue_job_id).with_for_update(skip_locked=True)
        )

    async def _publish_queue_event(
        self,
        db: AsyncSession,
        job: QueueJobRecord,
        event_type: EventType,
        *,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        body = {
            "queue_job_id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            **(payload or {}),
        }
        await event_bus.publish(
            db,
            event_type=event_type,
            severity=severity,
            session_id=job.session_id,
            agent_run_id=job.run_id,
            payload=body,
        )


async def execute_job(db: AsyncSession, job: QueueJob | QueueJobRecord) -> None:
    record = await _coerce_record(db, job)
    if record.job_type == JobType.AGENT_RUN:
        await execute_agent_run_job(db, record)
        return
    if record.job_type == JobType.PERMISSION_RESUME:
        await execute_permission_resume_job(db, record)
        return
    if record.job_type == JobType.HUMAN_INPUT_RESUME:
        await execute_human_input_resume_job(db, record)
        return
    if record.job_type == JobType.SESSION_COMPACTION:
        await execute_session_compaction_job(db, record)
        return
    raise ValueError(f"Unsupported queue job type: {record.job_type}")


async def execute_agent_run_job(db: AsyncSession, job: QueueJobRecord) -> None:
    from backend.app.runtime.agent_runner import agent_runner

    run_id = job.run_id or UUID(str(job.payload["agent_run_id"]))
    run = await db.get(AgentRun, run_id)
    if not run:
        raise KeyError(f"Agent run not found: {run_id}")
    session = await db.get(Session, run.session_id)
    if not session:
        raise KeyError(f"Session not found for agent run: {run.id}")
    user_id = _optional_uuid(job.payload.get("user_id"))
    await agent_runner.start_queued_run(db, session=session, run=run, user_id=user_id, job_id=str(job.id))


async def execute_permission_resume_job(db: AsyncSession, job: QueueJobRecord) -> None:
    from backend.app.permissions.service import permission_service
    from backend.app.runtime.agent_runner import agent_runner

    request_id = job.permission_request_id or UUID(str(job.payload["permission_request_id"]))
    context = await permission_service.load_approved_resume_context(db, request_id=request_id)
    user_id = _optional_uuid(job.payload.get("user_id"))
    await agent_runner.resume_after_permission(
        db,
        session=context.session,
        run=context.run,
        tool_call=context.tool_call,
        user_id=user_id,
        job_id=str(job.id),
    )


async def execute_human_input_resume_job(db: AsyncSession, job: QueueJobRecord) -> None:
    from backend.app.runtime.agent_runner import agent_runner
    from backend.app.runtime.human_input_service import human_input_service

    request_id = job.human_input_request_id or UUID(str(job.payload["human_input_request_id"]))
    context = await human_input_service.load_answered_resume_context(db, request_id=request_id)
    user_id = _optional_uuid(job.payload.get("user_id"))
    await agent_runner.resume_after_human_input(
        db,
        context=context,
        user_id=user_id,
        job_id=str(job.id),
    )


async def execute_session_compaction_job(db: AsyncSession, job: QueueJobRecord) -> None:
    from backend.app.runtime.agent_runner import agent_runner

    session_id = job.session_id or UUID(str(job.payload["session_id"]))
    session = await db.get(Session, session_id)
    if not session:
        raise KeyError(f"Session not found for compaction job: {session_id}")
    await agent_runner.run_compaction_job(
        db,
        session=session,
        source_message_end_id=_optional_uuid(job.payload.get("source_message_end_id")),
        job_id=str(job.id),
    )


async def mark_job_failed(db: AsyncSession, job: QueueJob | QueueJobRecord, *, error: str, final: bool) -> None:
    record = await _coerce_record(db, job)
    safe_error = redact_text(error)
    run = await _job_run(db, record)
    session = await _job_session(db, record, run=run)
    if final and run:
        run.status = "failed"
        run.error = safe_error
        run.completed_at = datetime.now(UTC)
    if final and session:
        session.status = "failed"
    await event_bus.publish(
        db,
        event_type=EventType.WORKER_JOB_DEAD_LETTERED if final else EventType.WORKER_JOB_FAILED,
        severity="error" if final else "warning",
        session_id=session.id if session else record.session_id,
        agent_run_id=run.id if run else record.run_id,
        payload={
            "queue_job_id": str(record.id),
            "job_type": record.job_type,
            "attempt_count": record.attempt_count,
            "max_attempts": record.max_attempts,
            "final": final,
            "error": safe_error,
        },
    )


def serialize_job(job: QueueJob | QueueJobRecord) -> dict[str, Any]:
    if isinstance(job, QueueJobRecord):
        return {
            "id": str(job.id),
            "queue_job_id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "priority": job.priority,
            "run_id": str(job.run_id) if job.run_id else None,
            "session_id": str(job.session_id) if job.session_id else None,
            "permission_request_id": str(job.permission_request_id) if job.permission_request_id else None,
            "human_input_request_id": str(job.human_input_request_id) if job.human_input_request_id else None,
            "user_message_id": str(job.user_message_id) if job.user_message_id else None,
            "idempotency_key": job.idempotency_key,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "claimed_by": job.claimed_by,
            "claimed_at": job.claimed_at.isoformat() if job.claimed_at else None,
            "available_at": job.available_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "failed_at": job.failed_at.isoformat() if job.failed_at else None,
            "last_error": job.last_error,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }
    return json.loads(job.model_dump_json())


async def _coerce_record(db: AsyncSession, job: QueueJob | QueueJobRecord) -> QueueJobRecord:
    if isinstance(job, QueueJobRecord):
        return job
    record = await db.get(QueueJobRecord, UUID(job.queue_job_id))
    if not record:
        raise KeyError(f"Queue job not found: {job.queue_job_id}")
    return record


async def _find_job_by_idempotency_key(db: AsyncSession, key: str) -> QueueJobRecord | None:
    if hasattr(db, "objects"):
        for (model, _row_id), row in db.objects.items():
            if model is QueueJobRecord and getattr(row, "idempotency_key", None) == key:
                return row
        return None
    return await db.scalar(select(QueueJobRecord).where(QueueJobRecord.idempotency_key == key))


async def _job_run(db: AsyncSession, job: QueueJobRecord) -> AgentRun | None:
    return await db.get(AgentRun, job.run_id) if job.run_id else None


async def _job_session(db: AsyncSession, job: QueueJobRecord, *, run: AgentRun | None = None) -> Session | None:
    if run:
        return await db.get(Session, run.session_id)
    return await db.get(Session, job.session_id) if job.session_id else None


def _optional_uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


runtime_queue = RuntimeQueue()
