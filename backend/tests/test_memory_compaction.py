from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.agents.registry import agent_registry
from backend.app.db.models import MemoryItem, QueueJobRecord, SessionSummary
from backend.app.main import create_app
from backend.app.memory.memory_service import MemoryCreate, memory_service
from backend.app.memory.summary_service import SummaryCreate, summary_service
from backend.app.queue.jobs import JobType, RuntimeQueue, execute_job
from backend.app.runtime.agent_runner import AgentRunner
from backend.app.runtime.context_builder import ContextMessage, context_builder
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import FakeProvider, make_session, make_user_message
from backend.tests.test_queue_jobs import FakeRedis, queue_settings


async def test_summary_service_create_fetch_and_supersede() -> None:
    session = make_session()
    db = FakeAsyncSession(objects=[session])

    first = await summary_service.create_summary(
        db,
        SummaryCreate(session=session, summary_type="rolling", content="First summary"),
    )
    active = await summary_service.list_active(db, session_id=session.id)

    assert active == [first]
    superseded = await summary_service.supersede_active(db, session_id=session.id, superseded_by=None)

    assert superseded == [first]
    assert first.status == "superseded"
    assert await summary_service.list_active(db, session_id=session.id) == []


async def test_summary_service_records_failed_attempt() -> None:
    session = make_session()
    db = FakeAsyncSession(objects=[session])

    failed = await summary_service.record_failed(
        db,
        session=session,
        summary_type="compaction",
        error="model unavailable",
    )

    assert failed.status == "failed"
    assert failed.content == "model unavailable"


async def test_memory_service_create_dedupe_text_search_and_visibility() -> None:
    session = make_session()
    db = FakeAsyncSession(objects=[session])

    first, created = await memory_service.create_item(
        db,
        MemoryCreate(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            source_type="project_note",
            content="Remember the release branch is main.",
            visibility="project",
        ),
    )
    duplicate, duplicate_created = await memory_service.create_item(
        db,
        MemoryCreate(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            source_type="project_note",
            content="Remember the release branch is main.",
            visibility="project",
        ),
    )
    rows = await memory_service.retrieve(
        db,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        query="release branch",
        visibility=["project"],
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == first.id
    assert rows == [first]
    assert first.metadata_json["embedding_status"] == "disabled"


async def test_context_builder_includes_active_summary_and_memory() -> None:
    session = make_session()
    message = make_user_message(session, "latest request")
    now = datetime.now(UTC)
    summary = SessionSummary(
        id=uuid4(),
        session_id=session.id,
        summary_type="rolling",
        content="Prior work: built queue runtime.",
        source_message_count=8,
        token_estimate=8,
        char_count=32,
        status="active",
        metadata_json={},
        created_at=now,
        updated_at=now,
    )
    memory = MemoryItem(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        kind="project_note",
        source_type="project_note",
        source_id=None,
        content="Project prefers local-only Ollama.",
        content_hash="abc",
        visibility="project",
        status="active",
        metadata_json={"embedding_status": "disabled"},
        created_at=now,
        updated_at=now,
    )
    db = FakeAsyncSession(messages=[message], objects=[session, summary, memory])

    bundle = await context_builder.build(db, session=session, agent=agent_registry.get("general"))

    assert "Prior work: built queue runtime." in bundle.prompt
    assert "Project prefers local-only Ollama." in bundle.prompt
    assert "USER:\nlatest request" in bundle.prompt


def test_context_builder_marks_compaction_needed_under_pressure() -> None:
    agent = agent_registry.get("general")
    bundle = context_builder.build_from_messages(
        agent=agent,
        tools=[],
        char_budget=3000,
        messages=[
            ContextMessage(role="user", content=f"old {index} " * 300)
            for index in range(8)
        ],
        summaries=[{"id": "summary-1", "summary_type": "rolling", "content": "stable summary"}],
        memory_items=[{"id": "memory-1", "source_type": "project_note", "content": "stable memory"}],
    )

    assert bundle.needs_compaction
    assert bundle.excluded_message_count > 0
    assert "stable summary" in bundle.prompt


async def test_agent_runner_mocked_compaction_creates_summary_and_memory(monkeypatch) -> None:
    session = make_session()
    messages = [make_user_message(session, "older context"), make_user_message(session, "newer context")]
    db = FakeAsyncSession(messages=messages, objects=[session])
    provider = FakeProvider(['{"type":"final","content":"Compact durable summary."}'])
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)

    summary = await AgentRunner().run_compaction_job(
        db,
        session=session,
        source_message_end_id=messages[-1].id,
        job_id="job-1",
    )

    assert summary is not None
    assert summary.summary_type == "compaction"
    assert summary.content == "Compact durable summary."
    assert any(isinstance(row, MemoryItem) and row.source_type == "session_summary" for row in db.added)


async def test_agent_runner_mocked_summary_failure_records_failed_summary(monkeypatch) -> None:
    session = make_session()
    db = FakeAsyncSession(messages=[make_user_message(session)], objects=[session])

    class BrokenProvider:
        async def generate(self, **_kwargs):
            import httpx

            request = httpx.Request("POST", "http://ollama/api/generate")
            response = httpx.Response(404, request=request, json={"error": "missing model"})
            raise httpx.HTTPStatusError("missing model", request=request, response=response)

    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: BrokenProvider())

    summary = await AgentRunner().create_session_summary(db, session=session)

    assert summary.status == "failed"
    assert "missing model" in summary.content


async def test_enqueue_session_compaction_is_idempotent() -> None:
    fake = FakeRedis()
    queue = RuntimeQueue(settings=queue_settings(), redis_factory=lambda: fake)
    session = make_session()
    db = FakeAsyncSession(objects=[session])
    message_id = uuid4()

    first = await queue.enqueue_session_compaction(
        db,
        session_id=session.id,
        source_message_end_id=message_id,
        user_id=session.created_by_user_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        reason="test",
    )
    second = await queue.enqueue_session_compaction(
        db,
        session_id=session.id,
        source_message_end_id=message_id,
        user_id=session.created_by_user_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        reason="test",
    )

    assert second.id == first.id
    assert first.job_type == JobType.SESSION_COMPACTION


async def test_worker_executes_compaction_job(monkeypatch) -> None:
    session = make_session()
    message = make_user_message(session)
    job = QueueJobRecord(
        id=uuid4(),
        job_type=JobType.SESSION_COMPACTION,
        status="running",
        session_id=session.id,
        payload={"session_id": str(session.id), "source_message_end_id": str(message.id)},
        idempotency_key=f"session_compaction:{session.id}:{message.id}",
        attempt_count=1,
        max_attempts=2,
        available_at=datetime.now(UTC),
    )
    db = FakeAsyncSession(messages=[message], objects=[session, job])
    provider = FakeProvider(['{"type":"final","content":"Worker compacted context."}'])
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)

    await execute_job(db, job)

    assert any(isinstance(row, SessionSummary) and row.content == "Worker compacted context." for row in db.added)


def test_memory_routes_are_in_openapi() -> None:
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]

    assert "/sessions/{session_id}/summaries" in paths
    assert "/memory/items" in paths
    assert "/sessions/{session_id}/memory" in paths
