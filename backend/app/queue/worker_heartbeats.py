from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings, get_settings
from backend.app.db.models import WorkerHeartbeat


@dataclass
class WorkerHeartbeatUpdate:
    worker_id: str
    hostname: str | None = None
    process_id: int | None = None
    status: str = "healthy"
    current_queue_job_id: UUID | None = None
    current_run_id: UUID | None = None
    claimed_jobs_delta: int = 0
    completed_jobs_delta: int = 0
    failed_jobs_delta: int = 0
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def worker_is_stale(
    row: WorkerHeartbeat,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(UTC)
    queue_settings = (settings or get_settings()).queue
    return row.last_heartbeat_at < current - timedelta(seconds=queue_settings.worker_stale_after_seconds)


def serialize_worker_heartbeat(
    row: WorkerHeartbeat,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    last_age_seconds = max((current - row.last_heartbeat_at).total_seconds(), 0.0)
    return {
        "id": str(row.id),
        "worker_id": row.worker_id,
        "hostname": row.hostname,
        "process_id": row.process_id,
        "status": row.status,
        "current_queue_job_id": str(row.current_queue_job_id) if row.current_queue_job_id else None,
        "current_run_id": str(row.current_run_id) if row.current_run_id else None,
        "claimed_jobs_count": row.claimed_jobs_count,
        "completed_jobs_count": row.completed_jobs_count,
        "failed_jobs_count": row.failed_jobs_count,
        "last_heartbeat_at": row.last_heartbeat_at.isoformat(),
        "last_heartbeat_age_seconds": round(last_age_seconds, 3),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "stopped_at": row.stopped_at.isoformat() if row.stopped_at else None,
        "stale": worker_is_stale(row, settings=settings, now=current),
        "metadata": row.metadata_json,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


class WorkerHeartbeatService:
    async def upsert(
        self,
        db: AsyncSession,
        update: WorkerHeartbeatUpdate,
    ) -> WorkerHeartbeat:
        row = await self._get_by_worker_id(db, update.worker_id)
        if row is None:
            row = WorkerHeartbeat(
                worker_id=update.worker_id,
                hostname=update.hostname,
                process_id=update.process_id,
                status=update.status,
                current_queue_job_id=update.current_queue_job_id,
                current_run_id=update.current_run_id,
                claimed_jobs_count=max(update.claimed_jobs_delta, 0),
                completed_jobs_count=max(update.completed_jobs_delta, 0),
                failed_jobs_count=max(update.failed_jobs_delta, 0),
                last_heartbeat_at=datetime.now(UTC),
                started_at=update.started_at,
                stopped_at=update.stopped_at,
                metadata_json=dict(update.metadata),
            )
            db.add(row)
            await db.flush()
            return row

        row.hostname = update.hostname or row.hostname
        row.process_id = update.process_id if update.process_id is not None else row.process_id
        row.status = update.status
        row.current_queue_job_id = update.current_queue_job_id
        row.current_run_id = update.current_run_id
        row.claimed_jobs_count += update.claimed_jobs_delta
        row.completed_jobs_count += update.completed_jobs_delta
        row.failed_jobs_count += update.failed_jobs_delta
        row.last_heartbeat_at = datetime.now(UTC)
        row.started_at = update.started_at or row.started_at
        row.stopped_at = update.stopped_at
        row.metadata_json = {**(row.metadata_json or {}), **update.metadata}
        await db.flush()
        return row

    async def get(self, db: AsyncSession, worker_id: str) -> WorkerHeartbeat | None:
        return await self._get_by_worker_id(db, worker_id)

    async def list_workers(self, db: AsyncSession) -> list[WorkerHeartbeat]:
        if hasattr(db, "objects"):
            rows = [row for (model, _row_id), row in db.objects.items() if model is WorkerHeartbeat]
            return sorted(rows, key=lambda row: row.last_heartbeat_at, reverse=True)
        return list((await db.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_heartbeat_at.desc()))).all())

    async def _get_by_worker_id(self, db: AsyncSession, worker_id: str) -> WorkerHeartbeat | None:
        if hasattr(db, "objects"):
            for (model, _row_id), row in db.objects.items():
                if model is WorkerHeartbeat and row.worker_id == worker_id:
                    return row
            return None
        return await db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))


worker_heartbeat_service = WorkerHeartbeatService()
