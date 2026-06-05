from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.routes_permissions import serialize_permission
from backend.app.core.events import EventType
from backend.app.core.redaction import REDACTED, redact_data, redact_text
from backend.app.runtime.event_bus import EventBus
from backend.app.tools.base import ToolContext
from backend.app.tools.read import ReadFileInput, ReadFileTool
from backend.tests.fakes import FakeAsyncSession


def test_bearer_token_redacted() -> None:
    assert redact_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456") == f"Authorization: Bearer {REDACTED}"


def test_env_assignments_are_redacted() -> None:
    output = redact_text("API_TOKEN=super-secret\nDATABASE_PASSWORD=hunter2\nSAFE=value")
    assert "super-secret" not in output
    assert "hunter2" not in output
    assert f"API_TOKEN={REDACTED}" in output
    assert "SAFE=value" in output


def test_private_key_block_redacted() -> None:
    text = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
    assert redact_text(text) == REDACTED


def test_nested_sensitive_keys_are_redacted() -> None:
    payload = redact_data({"metadata": {"token": "abc123", "safe": "ok"}})
    assert payload["metadata"]["token"] == REDACTED
    assert payload["metadata"]["safe"] == "ok"


async def test_event_payload_is_redacted_before_persistence_and_broadcast() -> None:
    db = FakeAsyncSession()
    bus = EventBus()
    websocket = _FakeWebSocket()
    session_id = uuid4()
    await bus.subscribe(websocket, session_id=session_id)

    event = await bus.publish(
        db,
        event_type=EventType.TOOL_CALL_COMPLETED,
        session_id=session_id,
        payload={"result": {"output": "Authorization: Bearer secret-token-value"}},
    )

    assert "secret-token-value" not in event.payload["result"]["output"]
    assert "secret-token-value" not in websocket.sent[-1]["payload"]["result"]["output"]


async def test_read_file_output_redacts_env_content(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("API_TOKEN=super-secret\nSAFE=value\n", encoding="utf-8")
    result = await ReadFileTool().run(
        ReadFileInput(path=".env"),
        ToolContext(
            organization_id=uuid4(),
            project_id=uuid4(),
            workspace_id=uuid4(),
            session_id=uuid4(),
            agent_id="test",
            workspace_root=workspace,
        ),
    )

    assert "super-secret" not in result.output["content"]
    assert f"API_TOKEN={REDACTED}" in result.output["content"]


def test_permission_serializer_returns_redacted_input_contract() -> None:
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=uuid4(),
        permission_key="write.file",
        resource="/workspace/.env",
        status="pending",
        input_json={"content": "API_TOKEN=super-secret"},
        metadata_json={"tool": "write.file", "reason": "secret"},
        created_at=now,
        resolved_at=None,
    )

    payload = serialize_permission(row)

    assert payload["agent_run_id"] == str(row.agent_run_id)
    assert payload["input"]["content"] == f"API_TOKEN={REDACTED}"
    assert payload["metadata"]["tool"] == "write.file"


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)
