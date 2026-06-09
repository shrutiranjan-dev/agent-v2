import asyncio
import json
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import WebSocket
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.redaction import redact_data
from backend.app.db.models import SystemEvent
from backend.app.queue.redis_client import get_redis, redis_transport_available


class EventBus:
    def __init__(self, *, redis_enabled: bool | None = None, redis_factory: Callable | None = None) -> None:
        self._session_subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._global_subscribers: set[WebSocket] = set()
        self._redis_tasks: dict[WebSocket, asyncio.Task] = {}
        self._redis_enabled_override = redis_enabled
        self._redis_factory = redis_factory or get_redis
        self._lock = asyncio.Lock()

    async def subscribe(self, websocket: WebSocket, session_id: UUID | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            if session_id:
                self._session_subscribers[str(session_id)].add(websocket)
            else:
                self._global_subscribers.add(websocket)
        if self._redis_enabled() and session_id:
            task = asyncio.create_task(self._redis_forward_loop(websocket, session_id))
            async with self._lock:
                self._redis_tasks[websocket] = task

    async def unsubscribe(self, websocket: WebSocket, session_id: UUID | None = None) -> None:
        async with self._lock:
            task = self._redis_tasks.pop(websocket, None)
            if session_id:
                self._session_subscribers[str(session_id)].discard(websocket)
            else:
                self._global_subscribers.discard(websocket)
        if task:
            task.cancel()

    async def publish(
        self,
        db: AsyncSession,
        *,
        event_type: str,
        payload: dict[str, Any],
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        session_id: UUID | None = None,
        agent_run_id: UUID | None = None,
        tool_call_id: UUID | None = None,
        severity: str = "info",
    ) -> SystemEvent:
        safe_payload = redact_data(payload)
        event = SystemEvent(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            event_type=event_type,
            severity=severity,
            payload=safe_payload,
        )
        db.add(event)
        await db.flush()
        envelope = self.serialize(event)
        if self._redis_enabled() and session_id:
            if await self._publish_redis(session_id=session_id, envelope=envelope):
                await self._broadcast(envelope, session_id=None)
            else:
                await self._broadcast(envelope, session_id=session_id)
        else:
            await self._broadcast(envelope, session_id=session_id)
        return event

    async def replay_session_events(
        self,
        db: AsyncSession,
        websocket: WebSocket,
        *,
        session_id: UUID,
        limit: int = 100,
    ) -> None:
        rows = list(
            (
                await db.scalars(
                    select(SystemEvent)
                    .where(SystemEvent.session_id == session_id)
                    .order_by(SystemEvent.created_at.desc(), SystemEvent.id.desc())
                    .limit(limit)
                )
            ).all()
        )
        for event in reversed(rows):
            await websocket.send_json(self.serialize(event))

    def serialize(self, event: SystemEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "type": event.event_type,
            "event_type": event.event_type,
            "severity": event.severity,
            "organization_id": str(event.organization_id) if event.organization_id else None,
            "project_id": str(event.project_id) if event.project_id else None,
            "workspace_id": str(event.workspace_id) if event.workspace_id else None,
            "session_id": str(event.session_id) if event.session_id else None,
            "agent_run_id": str(event.agent_run_id) if event.agent_run_id else None,
            "tool_call_id": str(event.tool_call_id) if event.tool_call_id else None,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }

    async def _broadcast(self, envelope: dict[str, Any], session_id: UUID | None) -> None:
        async with self._lock:
            targets = set(self._global_subscribers)
            if session_id:
                targets.update(self._session_subscribers.get(str(session_id), set()))
        if not targets:
            return
        asyncio.create_task(self._broadcast_send(envelope, targets))

    async def _broadcast_send(self, envelope: dict[str, Any], targets: set[WebSocket]) -> None:
        async def _send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(envelope), timeout=5)
            except (TimeoutError, Exception):
                raise

        results = await asyncio.gather(*[_send(ws) for ws in targets], return_exceptions=True)
        stale: list[WebSocket] = [
            ws for ws, exc in zip(targets, results, strict=True) if isinstance(exc, Exception)
        ]
        if stale:
            async with self._lock:
                for websocket in stale:
                    self._global_subscribers.discard(websocket)
                    for subscribers in self._session_subscribers.values():
                        subscribers.discard(websocket)

    def redis_channel(self, session_id: UUID) -> str:
        return f"session:{session_id}:events"

    def _redis_enabled(self) -> bool:
        if self._redis_enabled_override is not None:
            return self._redis_enabled_override
        return get_settings().redis.pubsub_enabled and redis_transport_available()

    async def _publish_redis(self, *, session_id: UUID, envelope: dict[str, Any]) -> bool:
        client = self._redis_factory()
        try:
            await asyncio.wait_for(
                client.publish(self.redis_channel(session_id), json.dumps(envelope, default=str)),
                timeout=5,
            )
            return True
        except (TimeoutError, RedisError, OSError, ValueError, TypeError):
            return False
        finally:
            close = getattr(client, "aclose", None)
            if close:
                try:
                    await asyncio.wait_for(close(), timeout=2)
                except (TimeoutError, Exception):
                    pass

    async def _redis_forward_loop(self, websocket: WebSocket, session_id: UUID) -> None:
        client = self._redis_factory()
        pubsub = client.pubsub()
        channel = self.redis_channel(session_id)
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_json(json.loads(data))
        except asyncio.CancelledError:
            raise
        except (AttributeError, RedisError, OSError, ValueError, TypeError):
            return
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            finally:
                close = getattr(client, "aclose", None)
                if close:
                    await close()


event_bus = EventBus()
