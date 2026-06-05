import asyncio
import logging
import os
import signal
import socket
from contextlib import suppress
from uuid import UUID

from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.logging import configure_logging
from backend.app.db.postgres import AsyncSessionLocal
from backend.app.queue.jobs import QueueDisabledError, RuntimeQueue, execute_job, mark_job_failed
from backend.app.runtime.event_bus import event_bus

logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(self, *, queue: RuntimeQueue | None = None) -> None:
        self.queue = queue or RuntimeQueue()
        self._stop = asyncio.Event()
        settings = get_settings()
        self.worker_id = settings.queue.worker_id or f"{socket.gethostname()}:{os.getpid()}"

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        settings = get_settings()
        if not settings.queue.enabled:
            raise QueueDisabledError("Worker cannot start while AP_QUEUE_ENABLED=false.")
        await self._publish_worker_event(EventType.WORKER_STARTED)
        logger.info("queue worker started", extra={"queue": settings.queue.name, "worker_id": self.worker_id})
        try:
            while not self._stop.is_set():
                message = await self.queue.dequeue()
                if not message:
                    continue
                async with AsyncSessionLocal() as db:
                    job = None
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
                        logger.info(
                            "queue job claimed",
                            extra={"queue_job_id": str(job.id), "job_type": job.job_type, "worker_id": self.worker_id},
                        )
                        await self.queue.start_claimed_job(db, job, worker_id=self.worker_id)
                        await execute_job(db, job)
                    except Exception as exc:
                        await db.rollback()
                        if job is None:
                            logger.exception(
                                "queue message failed before claim",
                                extra={"queue_job_id": message.queue_job_id, "worker_id": self.worker_id},
                            )
                            continue
                        async with AsyncSessionLocal() as failure_db:
                            failure_job = await failure_db.get(type(job), job.id)
                            if failure_job is None:
                                logger.exception(
                                    "queue job disappeared during failure handling",
                                    extra={"queue_job_id": str(job.id), "worker_id": self.worker_id},
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
                        logger.exception(
                            "queue job failed",
                            extra={"queue_job_id": str(job.id), "job_type": job.job_type, "requeued": requeued},
                        )
                    else:
                        await self.queue.complete_job(db, job, worker_id=self.worker_id)
                        await db.commit()
                        logger.info(
                            "queue job completed",
                            extra={"queue_job_id": str(job.id), "job_type": job.job_type, "worker_id": self.worker_id},
                        )
        finally:
            await self._publish_worker_event(EventType.WORKER_STOPPED)
            logger.info("queue worker stopped")

    async def _publish_worker_event(self, event_type: EventType) -> None:
        async with AsyncSessionLocal() as db:
            await event_bus.publish(db, event_type=event_type, payload={"worker": "backend-worker", "worker_id": self.worker_id})
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
