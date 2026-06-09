from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.db.models import AgentRun, Message, ModelCall, Session, ToolCall
from backend.app.runtime.agent_runner import AgentRunner
from backend.tests.fakes import FakeAsyncSession


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        raw = self.responses.pop(0)
        return {"response": raw, "latency_ms": 1, "prompt_eval_count": 2, "eval_count": 3}


def make_session(agent_id: str = "general") -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        created_by_user_id=uuid4(),
        title="Runtime test",
        agent_id=agent_id,
        model_provider="ollama",
        model_name="qwen2.5:latest",
        status="running",
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def make_user_message(session: Session, content: str = "hi") -> Message:
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        role="user",
        content=content,
        parts=[{"type": "text", "text": content}],
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


async def test_agent_runner_final_response_path_persists_run_message_and_model_call(monkeypatch) -> None:
    session = make_session()
    db = FakeAsyncSession(messages=[make_user_message(session)])
    provider = FakeProvider(['{"type":"final","content":"done"}'])
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)

    run = await AgentRunner().run(db, session=session, user_id=session.created_by_user_id)

    assert run.status == "completed"
    assert session.status == "idle"
    assert any(isinstance(row, ModelCall) and row.status == "completed" for row in db.added)
    assert any(isinstance(row, Message) and row.role == "assistant" and row.content == "done" for row in db.added)


async def test_agent_runner_tool_call_path_persists_tool_call_and_result(monkeypatch, tmp_path) -> None:
    session = make_session(agent_id="build")
    workspace_file = tmp_path / "README.md"
    workspace_file.write_text("hello from file\n", encoding="utf-8")
    db = FakeAsyncSession(messages=[make_user_message(session, "read README")])
    provider = FakeProvider(
        [
            '{"type":"tool_call","tool":"read.file","input":{"path":"README.md"}}',
            '{"type":"final","content":"read complete"}',
        ]
    )
    fake_settings = SimpleNamespace(
        workspace_root=tmp_path,
        runtime=SimpleNamespace(max_tool_repeats=3),
    )
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: fake_settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: fake_settings)

    run = await AgentRunner().run(db, session=session, user_id=session.created_by_user_id)

    assert run.status == "completed"
    assert any(isinstance(row, ToolCall) and row.tool_name == "read.file" for row in db.added)
    assert any(isinstance(row, Message) and row.role == "tool" for row in db.added)


async def test_agent_runner_invalid_json_fails_after_one_repair(monkeypatch) -> None:
    session = make_session()
    db = FakeAsyncSession(messages=[make_user_message(session)])
    provider = FakeProvider(["not json", "still not json"])
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)

    run = await AgentRunner().run(db, session=session, user_id=session.created_by_user_id)

    assert run.status == "failed"
    assert run.error == "Model returned invalid JSON after one repair attempt."
    assert len(provider.calls) == 2


async def test_agent_runner_stops_at_max_steps(monkeypatch) -> None:
    session = make_session(agent_id="tiny")
    db = FakeAsyncSession(messages=[make_user_message(session)])
    provider = FakeProvider(
        [
            '{"type":"tool_call","tool":"todo.write","input":{"todos":[{"content":"one","status":"pending","priority":"low"}]}}',
            '{"type":"tool_call","tool":"todo.write","input":{"todos":[{"content":"two","status":"pending","priority":"low"}]}}',
        ]
    )
    tiny_agent = AgentDefinition(
        id="tiny",
        name="Tiny",
        description="Test agent",
        mode="primary",
        model_config=ModelConfig(provider="ollama", model="qwen2.5:latest"),
        system_prompt="Return strict JSON.",
        allowed_tools=["todo.write"],
        permission_profile="default",
        max_steps=2,
    )
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)
    monkeypatch.setattr("backend.app.runtime.agent_runner.agent_registry.get", lambda _agent_id: tiny_agent)

    run = await AgentRunner().run(db, session=session, user_id=session.created_by_user_id)

    assert run.status == "failed"
    assert run.error == "Agent exceeded max steps: 2"
    assert run.step_count == 2


async def test_agent_runner_uses_run_model_name_when_session_differs(monkeypatch) -> None:
    session = make_session()
    run = AgentRun(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_id=session.agent_id,
        model_provider="ollama",
        model_name="gemma4:31b-cloud",
        status="queued",
    )
    db = FakeAsyncSession(messages=[make_user_message(session)])
    db.objects[(AgentRun, run.id)] = run
    provider = FakeProvider(['{"type":"final","content":"done"}'])
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)
    async def fake_publish(*a, **kw): pass
    monkeypatch.setattr("backend.app.runtime.agent_runner.event_bus.publish", fake_publish)

    result = await AgentRunner().start_queued_run(
        db, session=session, run=run, user_id=session.created_by_user_id, job_id="test-job"
    )

    assert result.status == "completed"
    assert len(provider.calls) >= 1
    assert provider.calls[0]["model"] == "gemma4:31b-cloud"
    assert provider.calls[0]["model"] != session.model_name
