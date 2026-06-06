from __future__ import annotations

"""State reducer tests for the Textual TUI.

The reducer is pure Python; these tests do not require a terminal.
"""

# ruff: noqa: E402

from backend.app.cli.tui_state import (
    ConnectionStatus,
    Message,
    RunStatus,
    TuiState,
    apply_event,
    clear_transient_state_for_session_switch,
    mark_connection,
    record_error,
    select_agent,
    select_session,
    set_agents,
    set_health,
    set_sessions,
)


def test_state_starts_idle_and_disconnected() -> None:
    state = TuiState()
    assert state.backend_health == "unknown"
    assert state.connection_status == ConnectionStatus.DISCONNECTED
    assert state.run_status == RunStatus.IDLE
    assert list(state.messages) == []
    assert list(state.events) == []
    assert state.latest_diff is None


def test_apply_message_created_appends_message() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "message.created",
            "payload": {
                "message": {
                    "id": "m1",
                    "role": "assistant",
                    "content": "hello",
                    "created_at": "2026-06-06T00:00:00Z",
                }
            },
        },
    )
    assert len(state.messages) == 1
    assert state.messages[0].role == "assistant"
    assert state.messages[0].content == "hello"


def test_apply_agent_run_lifecycle_updates_run_status() -> None:
    state = TuiState()
    apply_event(state, {"type": "agent_run.queued", "payload": {}})
    assert state.run_status == RunStatus.QUEUED
    apply_event(state, {"type": "agent_run.started", "payload": {}})
    assert state.run_status == RunStatus.RUNNING
    apply_event(state, {"type": "agent_run.waiting_permission", "payload": {}})
    assert state.run_status == RunStatus.WAITING_PERMISSION
    apply_event(state, {"type": "agent_run.resumed", "payload": {}})
    assert state.run_status == RunStatus.RUNNING
    apply_event(state, {"type": "agent_run.completed", "payload": {}})
    assert state.run_status == RunStatus.COMPLETED


def test_apply_agent_run_failed_records_error() -> None:
    state = TuiState()
    apply_event(state, {"type": "agent_run.failed", "payload": {"error": "boom"}})
    assert state.run_status == RunStatus.FAILED
    assert state.run_error == "boom"


def test_apply_permission_requested_creates_pending() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "permission.requested",
            "payload": {
                "id": "p1",
                "permission_key": "write.file",
                "resource": "x.py",
            },
        },
    )
    assert "p1" in state.pending_permissions
    assert state.pending_permissions["p1"].permission_key == "write.file"
    assert state.run_status == RunStatus.WAITING_PERMISSION


def test_apply_permission_approved_removes_pending() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "permission.requested",
            "payload": {"id": "p1", "permission_key": "write.file"},
        },
    )
    apply_event(
        state,
        {
            "type": "permission.approved",
            "payload": {"id": "p1"},
        },
    )
    assert "p1" not in state.pending_permissions


def test_apply_question_requested_and_answered() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "question.requested",
            "payload": {
                "id": "q1",
                "question": "Ship?",
                "choices": ["yes", "no"],
                "allow_free_text": False,
            },
        },
    )
    assert "q1" in state.pending_questions
    assert state.pending_questions["q1"].choices == ["yes", "no"]
    apply_event(
        state,
        {"type": "question.answered", "payload": {"id": "q1"}},
    )
    assert "q1" not in state.pending_questions


def test_apply_tool_call_updates_tool_timeline_and_diff() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "tool_call.completed",
            "payload": {
                "id": "t1",
                "tool_name": "edit.file",
                "status": "completed",
                "metadata": {
                    "diff_preview": "--- a\n+++ b\n-old\n+new\n",
                    "target_paths": ["x.py"],
                    "operation_type": "edit",
                    "risk_level": "medium",
                },
            },
        },
    )
    assert any(call.tool_call_id == "t1" for call in state.tool_calls)
    assert state.latest_diff is not None
    assert "x.py" in (state.latest_diff.get("target_paths") or [])


def test_apply_unknown_event_is_safe() -> None:
    state = TuiState()
    apply_event(state, {"type": "some.completely.unknown.event", "payload": {}})
    assert state.run_status == RunStatus.IDLE
    assert len(state.events) == 1


def test_event_dedupes_by_id() -> None:
    state = TuiState()
    event = {
        "id": "evt-1",
        "type": "message.created",
        "payload": {"message": {"id": "m1", "role": "assistant", "content": "hi"}},
    }
    apply_event(state, event)
    apply_event(state, event)
    assert len(state.messages) == 1
    assert len(state.events) == 1


def test_event_dedupes_by_type_and_timestamp() -> None:
    state = TuiState()
    event = {
        "type": "agent_run.step",
        "created_at": "2026-06-06T00:00:00Z",
        "payload": {"step": 1},
    }
    apply_event(state, event)
    apply_event(state, event)
    assert len(state.events) == 1


def test_queue_job_event_upserts() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "queue_job.created",
            "payload": {
                "id": "q1",
                "job_type": "agent_run",
                "status": "queued",
                "session_id": "s1",
                "attempt_count": 1,
                "max_attempts": 3,
            },
        },
    )
    apply_event(
        state,
        {
            "type": "queue_job.failed",
            "payload": {
                "id": "q1",
                "status": "failed",
                "last_error": "boom",
                "attempt_count": 3,
            },
        },
    )
    assert any(job.job_id == "q1" and job.status == "failed" for job in state.queue_jobs)
    assert any(job.last_error == "boom" for job in state.queue_jobs)


def test_set_agents_defaults_active_to_first() -> None:
    state = TuiState()
    set_agents(
        state,
        [
            {"id": "build", "name": "Build", "model_name": "m1"},
            {"id": "general", "name": "General", "model_name": "m2"},
        ],
    )
    assert state.active_agent_id == "build"
    assert state.active_model == "m1"
    set_agents(state, [{"id": "explore", "name": "Explore", "model_name": "m3"}])
    assert state.active_agent_id == "build"  # already set, do not override
    select_agent(state, "explore")
    assert state.active_agent_name == "Explore"
    assert state.active_model == "m3"


def test_select_session_clears_transient_state() -> None:
    state = TuiState()
    state.messages.append(
        Message(
            message_id="m1",
            role="user",
            content="x",
            created_at="2026-06-06T00:00:00Z",
        )
    )
    state.latest_diff = {"diff": "x"}
    set_sessions(
        state,
        [{"id": "s1", "title": "first"}, {"id": "s2", "title": "second"}],
    )
    select_session(state, "s1")
    assert state.active_session_id == "s1"
    assert state.active_session_title == "first"
    assert state.latest_diff is None
    select_session(state, "s2")
    assert state.active_session_id == "s2"
    select_session(state, None)
    assert state.active_session_id is None


def test_clear_transient_state_for_session_switch_resets_run_status() -> None:
    state = TuiState()
    state.run_status = RunStatus.WAITING_PERMISSION
    state.run_error = "stuck"
    clear_transient_state_for_session_switch(state)
    assert state.run_status == RunStatus.IDLE
    assert state.run_error == ""


def test_record_error_caps_at_ten() -> None:
    state = TuiState()
    for index in range(20):
        record_error(state, f"err-{index}")
    assert len(state.transient_errors) == 10
    assert state.transient_errors[0] == "err-10"


def test_mark_connection_updates_status_and_detail() -> None:
    state = TuiState()
    mark_connection(state, ConnectionStatus.CONNECTING, detail="negotiating")
    assert state.connection_status == ConnectionStatus.CONNECTING
    assert state.connection_detail == "negotiating"
    mark_connection(state, ConnectionStatus.FAILED, detail="timeout")
    assert state.connection_status == ConnectionStatus.FAILED


def test_set_health_updates_health() -> None:
    state = TuiState()
    set_health(state, "ok")
    assert state.backend_health == "ok"
    set_health(state, "degraded")
    assert state.backend_health == "degraded"


def test_snapshot_returns_serializable_dict() -> None:
    state = TuiState()
    set_agents(state, [{"id": "build", "name": "Build", "model_name": "m1"}])
    apply_event(
        state,
        {
            "type": "message.created",
            "payload": {"message": {"role": "assistant", "content": "hi"}},
        },
    )
    snap = state.snapshot()
    assert snap["backend_health"] == "unknown"
    assert snap["connection_status"] == "disconnected"
    assert snap["active_agent_id"] == "build"
    assert snap["active_model"] == "m1"
    assert len(snap["messages"]) == 1
    assert isinstance(snap["events"], list)
