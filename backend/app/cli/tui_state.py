"""Pure-Python state reducer for the TUI.

The reducer is intentionally independent from any Textual widget so it can be
unit tested without a live terminal. ``apply_event`` mutates a copy of
``TuiState`` and returns the new value. The Textual app drives the reducer
through ``update``; mock backends and tests can drive it the same way.

Dedupe rules:
- Events are deduplicated by ``event_id`` when present, falling back to
  ``(type, created_at, payload_hash)`` so reconnect replays do not double-print.
- Permission and human-input requests are deduplicated by their request id; if
  the same id is seen twice in the live stream, only the first transition
  mutates state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.app.cli.diff_preview import extract_diff_preview, should_show_diff

MAX_MESSAGES = 500
MAX_EVENTS = 1000
MAX_TOOL_CALLS = 200
MAX_QUEUE_JOBS = 200
MAX_DIFF_LINES = 200


class ConnectionStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


class RunStatus(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_PERMISSION = "waiting_permission"
    WAITING_HUMAN_INPUT = "waiting_human_input"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


def _payload_hash(payload: Any) -> str:
    try:
        encoded = json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        encoded = repr(payload)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _event_fingerprint(event: dict[str, Any]) -> tuple[str, str, str]:
    event_type = str(event.get("type") or event.get("event_type") or "")
    event_id = str(
        event.get("id")
        or event.get("event_id")
        or (event.get("payload") or {}).get("id")
        or ""
    )
    created = str(
        event.get("created_at")
        or event.get("timestamp")
        or (event.get("payload") or {}).get("created_at")
        or ""
    )
    return event_type, event_id, created


@dataclass
class Message:
    role: str
    content: str
    created_at: str = ""
    message_id: str = ""


@dataclass
class ToolCallRecord:
    tool_call_id: str
    tool_name: str
    status: str
    created_at: str = ""
    finished_at: str = ""
    error: str | None = None
    diff: str | None = None
    target_paths: list[str] = field(default_factory=list)
    operation_type: str = ""


@dataclass
class PermissionRequest:
    permission_id: str
    permission_key: str
    resource: str = ""
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanInputRequest:
    request_id: str
    question: str
    choices: list[str] = field(default_factory=list)
    allow_free_text: bool = False
    status: str = "pending"


@dataclass
class QueueJob:
    job_id: str
    job_type: str
    status: str
    session_id: str = ""
    attempts: str = "0/0"
    last_error: str | None = None


@dataclass
class TuiState:
    """In-memory state for the TUI session."""

    backend_health: str = "unknown"
    backend_url: str = ""
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    connection_detail: str = ""
    active_session_id: str | None = None
    active_session_title: str = ""
    active_agent_id: str | None = None
    active_agent_name: str = ""
    active_model: str = ""
    run_status: RunStatus = RunStatus.IDLE
    run_error: str = ""
    sessions: list[dict[str, Any]] = field(default_factory=list)
    agents: list[dict[str, Any]] = field(default_factory=list)
    messages: deque[Message] = field(default_factory=lambda: deque(maxlen=MAX_MESSAGES))
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    tool_calls: deque[ToolCallRecord] = field(default_factory=lambda: deque(maxlen=MAX_TOOL_CALLS))
    queue_jobs: deque[QueueJob] = field(default_factory=lambda: deque(maxlen=MAX_QUEUE_JOBS))
    pending_permissions: dict[str, PermissionRequest] = field(default_factory=dict)
    pending_questions: dict[str, HumanInputRequest] = field(default_factory=dict)
    latest_diff: dict[str, Any] | None = None
    transient_errors: list[str] = field(default_factory=list)
    seen_event_keys: set[str] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def clone(self) -> TuiState:
        with self._lock:
            return copy.deepcopy(self)

    def update(self, mutator) -> TuiState:
        with self._lock:
            mutator(self)
            return self

    # ------------------------------------------------------------------
    # Public accessors used by the Textual layer
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend_health": self.backend_health,
                "backend_url": self.backend_url,
                "connection_status": self.connection_status.value,
                "connection_detail": self.connection_detail,
                "active_session_id": self.active_session_id,
                "active_session_title": self.active_session_title,
                "active_agent_id": self.active_agent_id,
                "active_agent_name": self.active_agent_name,
                "active_model": self.active_model,
                "run_status": self.run_status.value,
                "run_error": self.run_error,
                "messages": [m.__dict__.copy() for m in self.messages],
                "events": list(self.events),
                "tool_calls": [t.__dict__.copy() for t in self.tool_calls],
                "queue_jobs": [q.__dict__.copy() for q in self.queue_jobs],
                "pending_permissions": [p.__dict__.copy() for p in self.pending_permissions.values()],
                "pending_questions": [q.__dict__.copy() for q in self.pending_questions.values()],
                "latest_diff": self.latest_diff,
                "transient_errors": list(self.transient_errors),
                "sessions": list(self.sessions),
                "agents": list(self.agents),
            }


# ---------------------------------------------------------------------------
# Reducer helpers
# ---------------------------------------------------------------------------


def _push_unique_event(state: TuiState, event: dict[str, Any]) -> bool:
    """Append an event to the state.events deque; return False if deduped."""
    event_type, event_id, created = _event_fingerprint(event)
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    # Scope id-based dedup by event type so that the same id appearing in two
    # distinct event families (e.g. ``permission.requested`` and
    # ``permission.approved``) is treated as a unique event.
    id_key = f"id:{event_type}:{event_id}" if event_id else ""
    type_key = f"type:{event_type}:ts:{created}:ph:{_payload_hash(payload)}"
    key_candidates = [id_key, type_key]
    for key in key_candidates:
        if not key:
            continue
        if key in state.seen_event_keys:
            return False
        state.seen_event_keys.add(key)
    state.events.append(event)
    return True


def _set_run_status(state: TuiState, status: RunStatus, *, error: str = "") -> None:
    state.run_status = status
    if error:
        state.run_error = error
    elif status != RunStatus.FAILED:
        state.run_error = ""


def _upsert_queue_job(state: TuiState, job: dict[str, Any]) -> None:
    job_id = str(
        job.get("id")
        or job.get("queue_job_id")
        or job.get("job_id")
        or ""
    )
    if not job_id:
        return
    new_job = QueueJob(
        job_id=job_id,
        job_type=str(job.get("job_type") or job.get("type") or "unknown"),
        status=str(job.get("status") or "unknown"),
        session_id=str(job.get("session_id") or ""),
        attempts=str(
            job.get("attempts")
            or f"{job.get('attempt_count', 0)}/{job.get('max_attempts', 0)}"
        ),
        last_error=job.get("last_error") or job.get("error"),
    )
    for index, existing in enumerate(state.queue_jobs):
        if existing.job_id == job_id:
            state.queue_jobs[index] = new_job
            return
    state.queue_jobs.append(new_job)


def _upsert_tool_call(state: TuiState, record: ToolCallRecord) -> None:
    for index, existing in enumerate(state.tool_calls):
        if existing.tool_call_id == record.tool_call_id:
            state.tool_calls[index] = record
            return
    state.tool_calls.append(record)


def _update_latest_diff(state: TuiState, payload: dict[str, Any]) -> None:
    if not should_show_diff(payload):
        return
    preview = extract_diff_preview(payload)
    if not preview.get("diff"):
        return
    diff_text = preview["diff"] or ""
    lines = diff_text.splitlines()
    if len(lines) > MAX_DIFF_LINES:
        diff_text = "\n".join(lines[:MAX_DIFF_LINES]) + f"\n... ({len(lines) - MAX_DIFF_LINES} more lines truncated)"
    state.latest_diff = {
        "title": str(payload.get("tool_name") or payload.get("permission_key") or "diff"),
        "diff": diff_text,
        "target_paths": list(preview.get("target_paths") or []),
        "operation_type": str(preview.get("operation_type") or ""),
        "risk_level": str(preview.get("risk_level") or "unknown"),
    }


# ---------------------------------------------------------------------------
# Top-level reducers
# ---------------------------------------------------------------------------


def apply_event(state: TuiState, event: dict[str, Any]) -> TuiState:
    """Apply a backend event to the state, returning the mutated copy."""
    if not isinstance(event, dict):
        return state
    with state._lock:
        if not _push_unique_event(state, event):
            return state
        event_type = str(event.get("type") or event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        _apply_typed_event(state, event_type, payload, event)
        return state


def _apply_typed_event(
    state: TuiState,
    event_type: str,
    payload: dict[str, Any],
    raw: dict[str, Any],
) -> None:
    if event_type == "message.created":
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        role = str(message.get("role", "assistant"))
        content = str(message.get("content", ""))
        if content:
            state.messages.append(
                Message(
                    role=role,
                    content=content,
                    created_at=str(message.get("created_at", "")),
                    message_id=str(message.get("id", "")),
                )
            )
        return
    if event_type == "agent_run.queued":
        _set_run_status(state, RunStatus.QUEUED)
        return
    if event_type in {"agent_run.started", "agent_run.step", "agent_run.resumed"}:
        _set_run_status(state, RunStatus.RUNNING)
        return
    if event_type == "agent_run.waiting_permission":
        _set_run_status(state, RunStatus.WAITING_PERMISSION)
        return
    if event_type == "agent_run.waiting_human_input":
        _set_run_status(state, RunStatus.WAITING_HUMAN_INPUT)
        return
    if event_type == "agent_run.completed":
        _set_run_status(state, RunStatus.COMPLETED)
        return
    if event_type == "agent_run.blocked":
        _set_run_status(state, RunStatus.BLOCKED)
        return
    if event_type == "agent_run.failed":
        _set_run_status(
            state,
            RunStatus.FAILED,
            error=str(payload.get("error") or payload.get("message") or "agent run failed"),
        )
        return
    if event_type.startswith("tool_call."):
        _apply_tool_event(state, event_type, payload, raw)
        return
    if event_type == "permission.requested":
        permission_id = str(
            payload.get("id")
            or payload.get("permission_request_id")
            or ""
        )
        if permission_id:
            state.pending_permissions[permission_id] = PermissionRequest(
                permission_id=permission_id,
                permission_key=str(payload.get("permission_key", "unknown")),
                resource=str(payload.get("resource", "")),
                status="pending",
                metadata=dict(payload.get("metadata") or {}),
            )
        _set_run_status(state, RunStatus.WAITING_PERMISSION)
        return
    if event_type in {"permission.approved", "permission.denied"}:
        permission_id = str(
            payload.get("id")
            or payload.get("permission_request_id")
            or ""
        )
        if permission_id and permission_id in state.pending_permissions:
            state.pending_permissions[permission_id].status = (
                "approved" if event_type.endswith("approved") else "denied"
            )
            state.pending_permissions.pop(permission_id, None)
        return
    if event_type == "question.requested":
        request_id = str(payload.get("id") or payload.get("human_input_request_id") or "")
        if request_id:
            state.pending_questions[request_id] = HumanInputRequest(
                request_id=request_id,
                question=str(payload.get("question", "Question requested")),
                choices=[str(choice) for choice in (payload.get("choices") or [])],
                allow_free_text=bool(payload.get("allow_free_text")),
                status="pending",
            )
        _set_run_status(state, RunStatus.WAITING_HUMAN_INPUT)
        return
    if event_type in {"question.answered", "question.cancelled"}:
        request_id = str(
            payload.get("id") or payload.get("human_input_request_id") or ""
        )
        if request_id:
            state.pending_questions.pop(request_id, None)
        return
    if event_type.startswith("queue_job."):
        _upsert_queue_job(state, payload)
        return
    if event_type.startswith("summary.") or event_type.startswith("compaction."):
        # Acknowledge but do not duplicate state
        return


def _apply_tool_event(
    state: TuiState,
    event_type: str,
    payload: dict[str, Any],
    _raw: dict[str, Any],
) -> None:
    tool_call_id = str(payload.get("id") or payload.get("tool_call_id") or "")
    if not tool_call_id:
        return
    status = str(payload.get("status") or event_type.rsplit(".", 1)[-1])
    record = ToolCallRecord(
        tool_call_id=tool_call_id,
        tool_name=str(payload.get("tool_name") or payload.get("tool") or "tool"),
        status=status,
        created_at=str(payload.get("created_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        error=payload.get("error"),
    )
    if should_show_diff(payload):
        preview = extract_diff_preview(payload)
        record.diff = preview.get("diff")
        record.target_paths = list(preview.get("target_paths") or [])
        record.operation_type = str(preview.get("operation_type") or "")
    _upsert_tool_call(state, record)
    _update_latest_diff(state, payload)


# ---------------------------------------------------------------------------
# Selection reducers
# ---------------------------------------------------------------------------


def select_session(state: TuiState, session_id: str | None) -> TuiState:
    state.active_session_id = session_id
    if session_id is None:
        state.active_session_title = ""
        return clear_transient_state_for_session_switch(state)
    for session in state.sessions:
        if str(session.get("id")) == session_id:
            state.active_session_title = str(session.get("title") or session_id)
            break
    else:
        state.active_session_title = session_id
    return clear_transient_state_for_session_switch(state)


def select_agent(state: TuiState, agent_id: str | None) -> TuiState:
    if agent_id is None:
        state.active_agent_id = None
        state.active_agent_name = ""
        state.active_model = ""
        return state
    state.active_agent_id = agent_id
    match = next(
        (a for a in state.agents if str(a.get("id")) == agent_id),
        None,
    )
    if match is not None:
        state.active_agent_name = str(match.get("name") or agent_id)
        state.active_model = str(match.get("model_name") or match.get("model") or "")
    else:
        state.active_agent_name = agent_id
        state.active_model = ""
    return state


def set_agents(state: TuiState, agents: Iterable[dict[str, Any]]) -> TuiState:
    state.agents = list(agents)
    if state.active_agent_id is None and state.agents:
        first = state.agents[0]
        state.active_agent_id = str(first.get("id"))
        state.active_agent_name = str(first.get("name") or first.get("id"))
        state.active_model = str(first.get("model_name") or first.get("model") or "")
    else:
        select_agent(state, state.active_agent_id)
    return state


def set_sessions(state: TuiState, sessions: Iterable[dict[str, Any]]) -> TuiState:
    state.sessions = list(sessions)
    return state


def record_error(state: TuiState, error: str) -> TuiState:
    if not error:
        return state
    state.transient_errors.append(str(error))
    state.transient_errors = state.transient_errors[-10:]
    return state


def clear_transient_state_for_session_switch(state: TuiState) -> TuiState:
    state.messages.clear()
    state.events.clear()
    state.tool_calls.clear()
    state.queue_jobs.clear()
    state.pending_permissions.clear()
    state.pending_questions.clear()
    state.latest_diff = None
    state.seen_event_keys.clear()
    state.run_status = RunStatus.IDLE
    state.run_error = ""
    return state


def mark_connection(
    state: TuiState,
    status: ConnectionStatus,
    *,
    detail: str = "",
) -> TuiState:
    state.connection_status = status
    state.connection_detail = detail
    return state


def set_health(state: TuiState, health: str) -> TuiState:
    state.backend_health = health
    return state
