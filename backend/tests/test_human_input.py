from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.db.models import HumanInputRequest, Message, QueueJobRecord, SystemEvent, ToolCall
from backend.app.queue.jobs import JobType, RuntimeQueue, execute_job
from backend.app.runtime.agent_runner import AgentRunner
from backend.app.runtime.human_input_service import (
    HumanInputStateError,
    HumanInputValidationError,
    human_input_service,
)
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import FakeProvider, make_session, make_user_message
from backend.tests.test_queue_jobs import FakeRedis, queue_settings


def runtime_settings(tmp_path):
    return SimpleNamespace(
        workspace_root=tmp_path,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
    )


async def prepare_waiting_question(monkeypatch, tmp_path, *, input_json: str | None = None):
    session = make_session(agent_id="general")
    db = FakeAsyncSession(messages=[make_user_message(session, "ask me")], objects=[session])
    provider = FakeProvider(
        [
            input_json
            or (
                '{"type":"tool_call","tool":"question.ask","input":'
                '{"question":"Pick a target","choices":["backend","frontend"],"allow_free_text":false}}'
            ),
            '{"type":"final","content":"thanks"}',
        ]
    )
    fake_settings = runtime_settings(tmp_path)
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: fake_settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: fake_settings)

    run = await AgentRunner().run(db, session=session, user_id=session.created_by_user_id)
    request = next(row for row in db.added if isinstance(row, HumanInputRequest))
    call = next(row for row in db.added if isinstance(row, ToolCall) and row.tool_name == "question.ask")
    return db, provider, session, run, request, call


async def test_question_ask_creates_durable_request_and_pauses_run(monkeypatch, tmp_path) -> None:
    db, _provider, session, run, request, call = await prepare_waiting_question(monkeypatch, tmp_path)

    assert run.status == "waiting_human_input"
    assert session.status == "waiting_human_input"
    assert call.status == "waiting_human_input"
    assert request.status == "pending"
    assert request.tool_call_id == call.id
    assert request.question == "Pick a target"
    assert request.metadata_json["choices"] == ["backend", "frontend"]
    assert any(isinstance(row, SystemEvent) and row.event_type == "question.requested" for row in db.added)
    assert any(isinstance(row, SystemEvent) and row.event_type == "agent_run.waiting_human_input" for row in db.added)


async def test_answer_human_input_resumes_run_and_completes_tool(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, call = await prepare_waiting_question(monkeypatch, tmp_path)

    context = await human_input_service.answer(
        db,
        request_id=request.id,
        answer="backend",
        user_id=session.created_by_user_id,
    )
    run = await AgentRunner().resume_after_human_input(
        db,
        context=context,
        user_id=session.created_by_user_id,
    )

    assert request.status == "answered"
    assert call.status == "completed"
    assert call.output_json["output"]["answer"] == "backend"
    assert call.output_json["output"]["selected_choice"] == "backend"
    assert run.status == "completed"
    assert any(isinstance(row, Message) and row.role == "tool" for row in db.added)
    assert any(isinstance(row, SystemEvent) and row.event_type == "question.answered" for row in db.added)
    assert any(
        isinstance(row, SystemEvent) and row.event_type == "agent_run.resumed_from_human_input"
        for row in db.added
    )


async def test_human_input_double_answer_is_blocked(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_question(monkeypatch, tmp_path)
    await human_input_service.answer(db, request_id=request.id, answer="backend", user_id=session.created_by_user_id)

    with pytest.raises(HumanInputStateError):
        await human_input_service.answer(db, request_id=request.id, answer="frontend", user_id=session.created_by_user_id)


async def test_invalid_choice_is_blocked(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_question(monkeypatch, tmp_path)

    with pytest.raises(HumanInputValidationError):
        await human_input_service.answer(db, request_id=request.id, answer="docs", user_id=session.created_by_user_id)


async def test_cancel_human_input_blocks_run(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, call = await prepare_waiting_question(monkeypatch, tmp_path)

    context = await human_input_service.cancel(
        db,
        request_id=request.id,
        user_id=session.created_by_user_id,
        message="not now",
    )

    assert context.request.status == "cancelled"
    assert context.run.status == "cancelled"
    assert context.session.status == "cancelled"
    assert call.status == "cancelled"
    assert call.output_json["error"]["code"] == "human_input_cancelled"
    assert any(isinstance(row, SystemEvent) and row.event_type == "question.cancelled" for row in db.added)

    with pytest.raises(HumanInputStateError):
        await human_input_service.answer(db, request_id=request.id, answer="backend", user_id=session.created_by_user_id)


async def test_expired_human_input_rejects_answer(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_question(
        monkeypatch,
        tmp_path,
        input_json='{"type":"tool_call","tool":"question.ask","input":{"question":"Timeout?","timeout_seconds":1}}',
    )
    request.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(HumanInputStateError):
        await human_input_service.answer(db, request_id=request.id, answer="yes", user_id=session.created_by_user_id)

    assert request.status == "expired"
    assert any(isinstance(row, SystemEvent) and row.event_type == "question.expired" for row in db.added)


async def test_enqueue_human_input_resume_is_idempotent(monkeypatch, tmp_path) -> None:
    db, _provider, session, run, request, _call = await prepare_waiting_question(monkeypatch, tmp_path)
    fake = FakeRedis()
    queue = RuntimeQueue(settings=queue_settings(), redis_factory=lambda: fake)

    first = await queue.enqueue_human_input_resume(
        db,
        human_input_request_id=request.id,
        agent_run_id=run.id,
        session_id=session.id,
        user_id=session.created_by_user_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
    )
    second = await queue.enqueue_human_input_resume(
        db,
        human_input_request_id=request.id,
        agent_run_id=run.id,
        session_id=session.id,
        user_id=session.created_by_user_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
    )

    assert second.id == first.id
    assert first.job_type == JobType.HUMAN_INPUT_RESUME


async def test_worker_resumes_answered_human_input_job(monkeypatch, tmp_path) -> None:
    db, _provider, session, run, request, call = await prepare_waiting_question(monkeypatch, tmp_path)
    await human_input_service.answer(db, request_id=request.id, answer="backend", user_id=session.created_by_user_id)
    job = QueueJobRecord(
        job_type=JobType.HUMAN_INPUT_RESUME,
        status="queued",
        run_id=run.id,
        session_id=session.id,
        human_input_request_id=request.id,
        payload={
            "human_input_request_id": str(request.id),
            "agent_run_id": str(run.id),
            "session_id": str(session.id),
            "user_id": str(session.created_by_user_id),
        },
        idempotency_key=f"human_input_resume:{request.id}",
        available_at=datetime.now(UTC),
    )
    db.add(job)
    await db.flush()

    await execute_job(db, job)

    assert call.status == "completed"
    assert run.status == "completed"
    assert any(isinstance(row, Message) and row.role == "assistant" and row.content == "thanks" for row in db.added)
