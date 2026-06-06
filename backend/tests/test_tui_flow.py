from __future__ import annotations

"""TUI-specific flow tests.

The TUI is a Rich-based interactive loop with explicit modal state machines.
These tests cover the run-loop entrypoint, agent switcher behavior, and the
modal duplicate-prevention state machine in isolation from a real backend.
"""

from io import StringIO

import pytest
from rich.console import Console

# ruff: noqa: E402
from backend.app.cli.api_client import CliApiError
from backend.app.cli.tui_app import _TuiState, run_tui
from backend.app.cli.tui_modals import DiffModal, HumanInputModal, PermissionModal


class _FakeClient:
    def __init__(self) -> None:
        self.agents = [
            {"id": "build", "name": "Build", "description": "coding agent", "model_name": "m1"},
            {"id": "general", "name": "General", "description": "chat agent", "model_name": "m2"},
        ]
        self.sent: list[dict] = []
        self.events: list[dict] = []
        self.permissions: list[dict] = []
        self.human_inputs: list[dict] = []
        self.retry_calls: list[str] = []
        self.approve_calls: list[str] = []
        self.deny_calls: list[str] = []
        self.answer_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[str] = []

    def list_agents(self):
        return list(self.agents)

    def create_session(self, *, title=None, agent_id="build", model_name=None):
        return {"id": "s-1", "title": title, "agent_id": agent_id}

    def list_sessions(self):
        return []

    def get_session(self, session_id):
        return {"session": {"id": session_id, "title": "demo"}}

    def send_message(self, session_id, *, content, agent_id=None, model_name=None):
        self.sent.append(
            {
                "session_id": session_id,
                "content": content,
                "agent_id": agent_id,
            }
        )
        return {"agent_run": {"id": "r1", "status": "queued"}}

    def list_events(self, session_id):
        return list(self.events)

    def list_permissions(self, *, session_id=None):
        return list(self.permissions)

    def list_human_input_requests(self, *, session_id=None, status=None):
        return list(self.human_inputs)

    def list_queue_jobs(self, *, session_id=None, limit=50):
        return []

    def queue_stats(self):
        return {"stats": {}}

    def retry_queue_job(self, job_id, *, reason="cli_retry"):
        self.retry_calls.append(job_id)
        return {"id": job_id, "status": "queued"}

    def approve_permission(self, permission_id, *, message=None):
        self.approve_calls.append(permission_id)

    def deny_permission(self, permission_id, *, message=None):
        self.deny_calls.append(permission_id)

    def answer_human_input(self, request_id, *, answer):
        self.answer_calls.append((request_id, answer))

    def cancel_human_input(self, request_id, *, message=None):
        self.cancel_calls.append(request_id)


def test_tui_state_welcome_loads_agents() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    assert state.agent_id == "build"
    assert len(state.agents) == 2


def test_tui_state_set_agent_picks_known_id() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.set_agent("general")
    assert state.agent_id == "general"
    state.set_agent("missing")
    assert state.agent_id == "general"


def test_tui_state_send_uses_active_agent() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.set_agent("general")
    state.session_id = "s-1"
    state.send_prompt("hi")
    assert fake.sent == [{"session_id": "s-1", "content": "hi", "agent_id": "general"}]


def test_tui_state_send_creates_session_when_missing() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.send_prompt("hi")
    assert state.session_id == "s-1"
    assert fake.sent[0]["agent_id"] == "build"


def test_tui_state_send_refuses_without_agent() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.agents = []
    state.agent_id = None
    state.send_prompt("hi")
    assert fake.sent == []


def test_tui_state_send_truncates_long_prompts() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.session_id = "s-1"
    state.send_prompt("x" * 5000)
    assert fake.sent == []


def test_tui_state_uses_agent_for_next_prompt_only() -> None:
    """Selecting a new agent must not retroactively change the session or past runs."""
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.session_id = "s-1"
    state.send_prompt("first")
    state.set_agent("general")
    state.send_prompt("second")
    assert fake.sent[0]["agent_id"] == "build"
    assert fake.sent[1]["agent_id"] == "general"
    assert state.session_id == "s-1"


def test_tui_state_does_not_mutate_past_runs() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.welcome()
    state.session_id = "s-1"
    state.send_prompt("first")
    sent_after_first = list(fake.sent)
    state.set_agent("general")
    state.send_prompt("second")
    assert sent_after_first == [{"session_id": "s-1", "content": "first", "agent_id": "build"}]


def test_tui_retry_dispatches_to_api() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state.session_id = "s-1"
    state.retry_job("job-1")
    assert fake.retry_calls == ["job-1"]


def test_tui_retry_surfaces_failure() -> None:
    class _Failing(_FakeClient):
        def retry_queue_job(self, job_id, *, reason="cli_retry"):
            raise CliApiError("HTTP 409: not retryable", status_code=409)

    state = _TuiState(client=_Failing(), console=Console(record=True))
    state.session_id = "s-1"
    state.retry_job("job-1")  # must not raise


def test_tui_permission_approve_dedupes() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state._register_permission(
        {"id": "p1", "permission_key": "write.file", "resource": "x.py"}
    )
    state.approve_permission("p1")
    state.approve_permission("p1")
    assert fake.approve_calls == ["p1"]


def test_tui_human_input_answer_dedupes() -> None:
    fake = _FakeClient()
    state = _TuiState(client=fake, console=Console(record=True))
    state._register_human_input(
        {
            "id": "q1",
            "question": "Ship?",
            "choices": ["yes", "no"],
            "allow_free_text": False,
        }
    )
    state.answer_human_input(["q1", "yes"])
    state.answer_human_input(["q1", "yes"])
    assert fake.answer_calls == [("q1", "yes")]


def test_tui_run_tui_quits_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    console = Console(file=StringIO(), record=True)
    import rich.prompt

    inputs = iter(["quit"])

    def _fake_ask(*_args, **_kwargs):
        return next(inputs)

    monkeypatch.setattr(rich.prompt.Prompt, "ask", _fake_ask)
    run_tui(fake, console=console)


def test_tui_run_tui_help_command_does_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    console = Console(file=StringIO(), record=True)
    import rich.prompt

    inputs = iter(["help", "quit"])

    def _fake_ask(*_args, **_kwargs):
        return next(inputs)

    monkeypatch.setattr(rich.prompt.Prompt, "ask", _fake_ask)
    run_tui(fake, console=console)


def test_tui_run_tui_send_uses_active_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    console = Console(file=StringIO(), record=True)
    import rich.prompt

    inputs = iter(["agent general", "send hi there", "quit"])

    def _fake_ask(*_args, **_kwargs):
        return next(inputs)

    monkeypatch.setattr(rich.prompt.Prompt, "ask", _fake_ask)
    run_tui(fake, console=console)
    assert fake.sent[-1]["agent_id"] == "general"
    assert fake.sent[-1]["content"] == "hi there"


def test_tui_run_tui_diff_command_no_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    console = Console(file=StringIO(), record=True)
    import rich.prompt

    inputs = iter(["use s-1", "diff", "quit"])

    def _fake_ask(*_args, **_kwargs):
        return next(inputs)

    monkeypatch.setattr(rich.prompt.Prompt, "ask", _fake_ask)
    run_tui(fake, console=console)


def test_tui_run_tui_retry_command(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    console = Console(file=StringIO(), record=True)
    import rich.prompt

    inputs = iter(["use s-1", "retry job-42", "quit"])

    def _fake_ask(*_args, **_kwargs):
        return next(inputs)

    monkeypatch.setattr(rich.prompt.Prompt, "ask", _fake_ask)
    run_tui(fake, console=console)
    assert fake.retry_calls == ["job-42"]


def test_diff_modal_no_diff_panel_safe() -> None:
    modal = DiffModal(events=[], max_lines=10)
    panel = modal.render()
    console = Console(record=True, width=200)
    console.print(panel)
    output = console.export_text()
    assert "No diff available" in output


def test_permission_modal_renders_text_panel() -> None:
    modal = PermissionModal(
        permission={"id": "p1", "permission_key": "write.file", "resource": "x.py"}
    )
    console = Console(record=True, width=200)
    console.print(modal.render())
    output = console.export_text()
    assert "Permission" in output
    assert "write.file" in output


def test_human_input_modal_renders_choices() -> None:
    modal = HumanInputModal(
        request={
            "id": "q1",
            "question": "Ship?",
            "choices": ["yes", "no"],
            "allow_free_text": False,
        }
    )
    console = Console(record=True, width=200)
    console.print(modal.render())
    output = console.export_text()
    assert "Ship" in output
    assert "yes" in output
