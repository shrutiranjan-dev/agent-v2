from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.postgres import get_session
from backend.app.queue.jobs import (
    QueueJobStateError,
    cancel_job,
    get_job_record,
    list_jobs,
    queue_stats,
    retry_job,
    runtime_queue,
    serialize_job,
)
from backend.app.queue.worker_heartbeats import (
    serialize_worker_heartbeat,
    worker_heartbeat_service,
    worker_is_stale,
)

router = APIRouter(prefix="/queue", tags=["queue"])
workers_router = APIRouter(tags=["queue"])


class QueueJobAction(BaseModel):
    reason: str = Field(default="manual_operator_action", min_length=1, max_length=200)
    publish: bool = True


@router.get("/stats")
async def get_queue_stats(db: AsyncSession = Depends(get_session)) -> dict:
    return {"stats": await queue_stats(db), "queue_enabled": runtime_queue.enabled}


@router.get("/jobs")
async def get_queue_jobs(
    status: str | None = None,
    job_type: str | None = None,
    session_id: UUID | None = None,
    run_id: UUID | None = None,
    permission_request_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await list_jobs(
        db,
        status=status,
        job_type=job_type,
        session_id=session_id,
        run_id=run_id,
        permission_request_id=permission_request_id,
        limit=max(1, min(limit, 500)),
        offset=max(offset, 0),
    )
    return {"jobs": [serialize_job(row) for row in rows]}


@router.get("/jobs/{queue_job_id}")
async def get_queue_job(queue_job_id: UUID, db: AsyncSession = Depends(get_session)) -> dict:
    row = await get_job_record(db, queue_job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Queue job not found: {queue_job_id}")
    return {"job": serialize_job(row)}


@router.post("/jobs/{queue_job_id}/retry")
async def retry_queue_job(
    queue_job_id: UUID,
    payload: QueueJobAction | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        row = await retry_job(db, queue_job_id=queue_job_id, reason=payload.reason if payload else "manual_retry")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QueueJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    should_publish = payload.publish if payload else True
    if should_publish and runtime_queue.enabled:
        await runtime_queue.publish_job(row)
    return {"job": serialize_job(row)}


@router.post("/jobs/{queue_job_id}/cancel")
async def cancel_queue_job(
    queue_job_id: UUID,
    payload: QueueJobAction | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        row = await cancel_job(db, queue_job_id=queue_job_id, reason=payload.reason if payload else "manual_cancel")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QueueJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"job": serialize_job(row)}


async def _get_workers_payload(db: AsyncSession) -> dict:
    rows = await worker_heartbeat_service.list_workers(db)
    return {"workers": [serialize_worker_heartbeat(row) for row in rows]}


async def _get_worker_stats_payload(db: AsyncSession) -> dict:
    rows = await worker_heartbeat_service.list_workers(db)
    stale = sum(1 for row in rows if worker_is_stale(row))
    active = [row for row in rows if not worker_is_stale(row)]
    return {
        "stats": {
            "total": len(rows),
            "active": len(active),
            "stale": stale,
            "healthy": sum(1 for row in active if row.status == "healthy"),
            "busy": sum(1 for row in active if row.current_queue_job_id is not None),
            "stopped": sum(1 for row in rows if row.stopped_at is not None or row.status == "stopped"),
            "failed": sum(1 for row in rows if row.status == "failed"),
            "claimed_jobs_count": sum(row.claimed_jobs_count for row in rows),
            "completed_jobs_count": sum(row.completed_jobs_count for row in rows),
            "failed_jobs_count": sum(row.failed_jobs_count for row in rows),
        }
    }


@router.get("/workers")
async def get_queue_workers(db: AsyncSession = Depends(get_session)) -> dict:
    return await _get_workers_payload(db)


@workers_router.get("/workers")
async def get_workers(db: AsyncSession = Depends(get_session)) -> dict:
    return await _get_workers_payload(db)


@workers_router.get("/workers/stats")
async def get_workers_stats(db: AsyncSession = Depends(get_session)) -> dict:
    return await _get_worker_stats_payload(db)
