import asyncio
import logging
import os
import signal
import socket
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.logging import configure_logging
from backend.app.db.models import QueueJobRecord
from backend.app.db.postgres import AsyncSessionLocal
from backend.app.queue.jobs import QueueDisabledError, RuntimeQueue, execute_job, mark_job_failed
from backend.app.queue.worker_heartbeats import WorkerHeartbeatUpdate, worker_heartbeat_service
from backend.app.runtime.event_bus import event_bus

logger = logging.getLogger(__name__)


@dataclass
class WorkerRuntimeState:
    status: str = "starting"
    current_queue_job_id: UUID | None = None
    current_run_id: UUID | None = None
    claimed_jobs_count: int = 0
    completed_jobs_count: int = 0
    failed_jobs_count: int = 0
    last_error: str | None = None


class QueueWorker:
    def __init__(self, *, queue: RuntimeQueue | None = None) -> None:
        self.queue = queue or RuntimeQueue()
        self._stop = asyncio.Event()
        self._state_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None
        settings = get_settings()
        self.worker_id = settings.queue.worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.hostname = socket.gethostname()
        self.process_id = os.getpid()
        self.state = WorkerRuntimeState()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        settings = get_settings()
        if not settings.queue.enabled:
            raise QueueDisabledError("Worker cannot start while AP_QUEUE_ENABLED=false.")
        await self._set_state(status="starting")
        await self._write_heartbeat(started=True)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        await self._publish_worker_event(EventType.WORKER_STARTED)
        await self._set_state(status="healthy")
        await self._write_heartbeat()
        logger.info(
            "queue worker started",
            extra={"queue": settings.queue.name, "worker_id": self.worker_id},
        )
        try:
            while not self._stop.is_set():
                message = await self.queue.dequeue()
                if not message:
                    continue
                async with AsyncSessionLocal() as db:
                    job = None
                    job_id: UUID | None = None
                    job_type: str | None = None
                    try:
                        job = await self.queue.claim_job(
                            db,
                            queue_job_id=UUID(message.queue_job_id),
                            worker_id=self.worker_id,
                        )
                        if job is None:
                            await db.rollback()
                            logger.info(
                                "queue message ignored",
                                extra={"queue_job_id": message.queue_job_id, "worker_id": self.worker_id},
                            )
                            continue
                        job_id = job.id
                        job_type = job.job_type
                        await self._set_state(
                            status="busy",
                            current_queue_job_id=job_id,
                            current_run_id=job.run_id,
                            claimed_jobs_delta=1,
                        )
                        await self._write_heartbeat()
                        logger.info(
                            "queue job claimed",
                            extra={"queue_job_id": str(job_id), "job_type": job_type, "worker_id": self.worker_id},
                        )
                        await self.queue.start_claimed_job(db, job, worker_id=self.worker_id)
                        await execute_job(db, job)
                    except Exception as exc:
                        await db.rollback()
                        if job_id is None:
                            logger.exception(
                                "queue message failed before claim",
                                extra={"queue_job_id": message.queue_job_id, "worker_id": self.worker_id},
                            )
                            continue
                        async with AsyncSessionLocal() as failure_db:
                            failure_job = await failure_db.get(QueueJobRecord, job_id)
                            if failure_job is None:
                                logger.exception(
                                    "queue job disappeared during failure handling",
                                    extra={"queue_job_id": str(job_id), "worker_id": self.worker_id},
                                )
                                continue
                            requeued = await self.queue.fail_job(
                                failure_db,
                                failure_job,
                                worker_id=self.worker_id,
                                error=str(exc),
                            )
                            await mark_job_failed(failure_db, failure_job, error=str(exc), final=not requeued)
                            await failure_db.commit()
                        if requeued:
                            await self.queue.publish_job(failure_job)
                        await self._set_state(
                            status="healthy",
                            current_queue_job_id=None,
                            current_run_id=None,
                            failed_jobs_delta=1,
                            last_error=str(exc),
                        )
                        await self._write_heartbeat()
                        logger.exception(
                            "queue job failed",
                            extra={"queue_job_id": str(job_id), "job_type": job_type, "requeued": requeued},
                        )
                    else:
                        await self.queue.complete_job(db, job, worker_id=self.worker_id)
                        await db.commit()
                        await self._set_state(
                            status="healthy",
                            current_queue_job_id=None,
                            current_run_id=None,
                            completed_jobs_delta=1,
                            last_error=None,
                        )
                        await self._write_heartbeat()
                        logger.info(
                            "queue job completed",
                            extra={"queue_job_id": str(job.id), "job_type": job.job_type, "worker_id": self.worker_id},
                        )
        except Exception as exc:
            await self._set_state(status="failed", last_error=str(exc))
            await self._write_heartbeat()
            await self._publish_worker_event(EventType.WORKER_FAILED, severity="error")
            raise
        finally:
            self.request_stop()
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            await self._set_state(status="stopped", current_queue_job_id=None, current_run_id=None)
            await self._write_heartbeat(stopped=True)
            await self._publish_worker_event(EventType.WORKER_STOPPED)
            logger.info("queue worker stopped")

    async def _heartbeat_loop(self) -> None:
        interval = get_settings().queue.worker_heartbeat_interval_seconds
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                await self._write_heartbeat()

    async def _set_state(
        self,
        *,
        status: str | None = None,
        current_queue_job_id: UUID | None | object = ...,
        current_run_id: UUID | None | object = ...,
        claimed_jobs_delta: int = 0,
        completed_jobs_delta: int = 0,
        failed_jobs_delta: int = 0,
        last_error: str | None | object = ...,
    ) -> None:
        async with self._state_lock:
            if status is not None:
                self.state.status = status
            if current_queue_job_id is not ...:
                self.state.current_queue_job_id = current_queue_job_id
            if current_run_id is not ...:
                self.state.current_run_id = current_run_id
            self.state.claimed_jobs_count += claimed_jobs_delta
            self.state.completed_jobs_count += completed_jobs_delta
            self.state.failed_jobs_count += failed_jobs_delta
            if last_error is not ...:
                self.state.last_error = last_error

    async def _write_heartbeat(self, *, started: bool = False, stopped: bool = False) -> None:
        async with self._state_lock:
            metadata: dict[str, str] = {"worker": "backend-worker"}
            if self.state.last_error:
                metadata["last_error"] = self.state.last_error
            update = WorkerHeartbeatUpdate(
                worker_id=self.worker_id,
                hostname=self.hostname,
                process_id=self.process_id,
                status=self.state.status,
                current_queue_job_id=self.state.current_queue_job_id,
                current_run_id=self.state.current_run_id,
                claimed_jobs_delta=0,
                completed_jobs_delta=0,
                failed_jobs_delta=0,
                started_at=datetime.now(UTC) if started else None,
                stopped_at=datetime.now(UTC) if stopped else None,
                metadata=metadata,
            )
            claimed_total = self.state.claimed_jobs_count
            completed_total = self.state.completed_jobs_count
            failed_total = self.state.failed_jobs_count
        async with AsyncSessionLocal() as db:
            row = await worker_heartbeat_service.get(db, self.worker_id)
            if row is None:
                update.claimed_jobs_delta = claimed_total
                update.completed_jobs_delta = completed_total
                update.failed_jobs_delta = failed_total
            else:
                update.claimed_jobs_delta = claimed_total - row.claimed_jobs_count
                update.completed_jobs_delta = completed_total - row.completed_jobs_count
                update.failed_jobs_delta = failed_total - row.failed_jobs_count
            await worker_heartbeat_service.upsert(db, update)
            await db.commit()

    async def _publish_worker_event(self, event_type: EventType, *, severity: str = "info") -> None:
        async with self._state_lock:
            payload = {
                "worker": "backend-worker",
                "worker_id": self.worker_id,
                "status": self.state.status,
                "current_queue_job_id": str(self.state.current_queue_job_id) if self.state.current_queue_job_id else None,
                "current_run_id": str(self.state.current_run_id) if self.state.current_run_id else None,
                "claimed_jobs_count": self.state.claimed_jobs_count,
                "completed_jobs_count": self.state.completed_jobs_count,
                "failed_jobs_count": self.state.failed_jobs_count,
            }
            if self.state.last_error:
                payload["last_error"] = self.state.last_error
        async with AsyncSessionLocal() as db:
            await event_bus.publish(
                db,
                event_type=event_type,
                severity=severity,
                payload=payload,
            )
            await db.commit()


async def amain() -> None:
    configure_logging(get_settings())
    worker = QueueWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)
    await worker.run()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
