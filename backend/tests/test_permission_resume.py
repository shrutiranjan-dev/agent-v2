from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.db.models import (
    Message,
    PermissionRequest,
    Session,
    SystemEvent,
    ToolCall,
)
from backend.app.permissions.service import (
    PermissionResumeSecurityError,
    PermissionStateError,
    permission_service,
)
from backend.app.runtime.agent_runner import AgentRunner
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import FakeProvider


def make_session() -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        created_by_user_id=uuid4(),
        title="Permission resume",
        agent_id="build",
        model_provider="ollama",
        model_name="qwen2.5:latest",
        status="running",
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def make_message(session: Session) -> Message:
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        role="user",
        content="write a file",
        parts=[{"type": "text", "text": "write a file"}],
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def runtime_settings(tmp_path):
    return SimpleNamespace(
        workspace_root=tmp_path,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
    )


async def prepare_waiting_permission(monkeypatch, tmp_path):
    session = make_session()
    db = FakeAsyncSession(messages=[make_message(session)], objects=[session])
    provider = FakeProvider(
        [
            '{"type":"tool_call","tool":"write.file","input":{"path":"approved.txt","content":"ok"}}',
            '{"type":"final","content":"done"}',
        ]
    )
    fake_settings = runtime_settings(tmp_path)
    monkeypatch.setattr("backend.app.runtime.agent_runner.get_provider", lambda _provider: provider)
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: fake_settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: fake_settings)

    run = await AgentRunner().run(db, session=session, user_id=session.created_by_user_id)
    request = next(row for row in db.added if isinstance(row, PermissionRequest))
    call = next(row for row in db.added if isinstance(row, ToolCall))
    return db, provider, session, run, request, call


async def test_ask_permission_creates_pending_request_and_pauses_run(monkeypatch, tmp_path) -> None:
    db, _provider, session, run, request, call = await prepare_waiting_permission(monkeypatch, tmp_path)

    assert run.status == "waiting_permission"
    assert session.status == "waiting_permission"
    assert request.status == "pending"
    assert request.tool_call_id == call.id
    assert call.status == "waiting_permission"
    assert call.permission_request_id == request.id
    assert any(
        isinstance(row, SystemEvent) and row.event_type == "permission.requested"
        for row in db.added
    )


async def test_approve_permission_resumes_run_and_executes_tool(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_permission(monkeypatch, tmp_path)

    context = await permission_service.approve(
        db,
        request_id=request.id,
        user_id=session.created_by_user_id,
        message="approved",
    )
    run = await AgentRunner().resume_after_permission(
        db,
        session=context.session,
        run=context.run,
        tool_call=context.tool_call,
        user_id=session.created_by_user_id,
    )

    assert request.status == "approved"
    assert run.status == "completed"
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "ok"
    assert any(
        isinstance(row, SystemEvent) and row.event_type == "permission.approved"
        for row in db.added
    )


async def test_deny_permission_blocks_run_and_does_not_execute_tool(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, call = await prepare_waiting_permission(monkeypatch, tmp_path)

    context = await permission_service.deny(
        db,
        request_id=request.id,
        user_id=session.created_by_user_id,
        message="nope",
    )

    assert context.request.status == "denied"
    assert context.run.status == "failed"
    assert call.status == "denied"
    assert not (tmp_path / "approved.txt").exists()
    assert any(isinstance(row, SystemEvent) and row.event_type == "permission.denied" for row in db.added)


async def test_mismatched_input_hash_blocks_resume(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_permission(monkeypatch, tmp_path)
    request.metadata_json["input_hash"] = "bad"

    with pytest.raises(PermissionResumeSecurityError):
        await permission_service.approve(
            db,
            request_id=request.id,
            user_id=session.created_by_user_id,
        )

    assert any(
        isinstance(row, SystemEvent) and row.event_type == "permission.resume_blocked"
        for row in db.added
    )


async def test_approval_cannot_be_reused(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_permission(monkeypatch, tmp_path)
    await permission_service.approve(db, request_id=request.id, user_id=session.created_by_user_id)

    with pytest.raises(PermissionStateError):
        await permission_service.approve(db, request_id=request.id, user_id=session.created_by_user_id)


async def test_denied_request_cannot_later_be_approved(monkeypatch, tmp_path) -> None:
    db, _provider, session, _run, request, _call = await prepare_waiting_permission(monkeypatch, tmp_path)
    await permission_service.deny(db, request_id=request.id, user_id=session.created_by_user_id)

    with pytest.raises(PermissionStateError):
        await permission_service.approve(db, request_id=request.id, user_id=session.created_by_user_id)
