from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.events import EventType
from backend.app.db.models import SystemEvent
from backend.app.runtime.event_bus import EventBus
from backend.tests.fakes import FakeAsyncSession, FakeScalarResult


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class FakeEventSession(FakeAsyncSession):
    def __init__(self, events: list[SystemEvent]) -> None:
        super().__init__()
        self.events = events

    async def scalars(self, _statement):
        return FakeScalarResult(self.events)


class FakeRedisClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    async def aclose(self) -> None:
        self.closed = True


async def test_event_publish_persists_and_broadcasts_session_event() -> None:
    db = FakeAsyncSession()
    bus = EventBus()
    websocket = FakeWebSocket()
    session_id = uuid4()
    await bus.subscribe(websocket, session_id=session_id)

    event = await bus.publish(
        db,
        event_type=EventType.MESSAGE_CREATED,
        session_id=session_id,
        payload={"message": {"content": "hello"}},
    )

    assert event in db.added
    assert websocket.sent[-1]["event_type"] == "message.created"
    assert websocket.sent[-1]["session_id"] == str(session_id)


async def test_event_replay_sends_persisted_session_events() -> None:
    session_id = uuid4()
    event = SystemEvent(
        id=uuid4(),
        session_id=session_id,
        event_type=EventType.AGENT_RUN_STARTED,
        severity="info",
        payload={"id": "run-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    websocket = FakeWebSocket()

    await EventBus().replay_session_events(FakeEventSession([event]), websocket, session_id=session_id)

    assert websocket.sent == [
        {
            "id": str(event.id),
            "type": "agent_run.started",
            "event_type": "agent_run.started",
            "severity": "info",
            "organization_id": None,
            "project_id": None,
            "workspace_id": None,
            "session_id": str(session_id),
            "agent_run_id": None,
            "tool_call_id": None,
            "payload": {"id": "run-1"},
            "created_at": event.created_at.isoformat(),
        }
    ]


async def test_redis_bus_path_uses_session_channel() -> None:
    db = FakeAsyncSession()
    session_id = uuid4()
    fake_redis = FakeRedisClient()
    bus = EventBus(redis_enabled=True, redis_factory=lambda: fake_redis)

    await bus.publish(
        db,
        event_type=EventType.PERMISSION_REQUESTED,
        session_id=session_id,
        payload={"id": "permission-1"},
    )

    assert fake_redis.published
    channel, payload = fake_redis.published[0]
    assert channel == f"session:{session_id}:events"
    assert "permission.requested" in payload
    assert fake_redis.closed
