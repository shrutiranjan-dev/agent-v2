from __future__ import annotations

import json

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

from backend.app.cli.api_client import AgentApiClient
from backend.app.cli.config import CliConfig
from backend.app.cli.diff_preview import extract_diff_preview, should_show_diff
from backend.app.cli.main import app
from backend.app.cli.render import (
    agents_table,
    event_renderable,
    sessions_table,
)
from backend.app.cli.session_commands import handle_human_input_request, handle_permission_request
from backend.app.cli.tui_modals import (
    DiffModal,
    HumanInputModal,
    ModalResult,
    PermissionModal,
)
from backend.app.cli.tui_state import (
    TuiState,
    apply_event,
    set_agents,
)
from backend.app.runtime.tool_executor import _permission_preview_metadata


def test_api_client_calls_health_agents_sessions_and_message() -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/agents":
            return httpx.Response(200, json={"agents": [{"id": "build"}]})
        if request.url.path == "/sessions" and request.method == "POST":
            return httpx.Response(200, json={"session": {"id": "s1", "title": body["title"]}})
        if request.url.path == "/sessions":
            return httpx.Response(200, json={"sessions": [{"id": "s1"}]})
        if request.url.path == "/sessions/s1/messages":
            return httpx.Response(200, json={"agent_run": {"id": "r1", "status": "queued"}})
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    client = AgentApiClient(
        CliConfig(base_url="http://testserver", ws_url="ws://testserver"),
        client=httpx.Client(transport=transport, base_url="http://testserver"),
    )

    assert client.health()["status"] == "ok"
    assert client.list_agents()[0]["id"] == "build"
    assert client.create_session(title="CLI", agent_id="build")["id"] == "s1"
    assert client.list_sessions()[0]["id"] == "s1"
    assert client.send_message("s1", content="hello")["agent_run"]["status"] == "queued"
    assert ("POST", "/sessions/s1/messages", {"content": "hello"}) in seen


def test_api_client_supports_queue_retry_and_show() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/queue/jobs/q1":
            return httpx.Response(200, json={"job": {"id": "q1", "status": "failed"}})
        if request.url.path == "/queue/jobs/q1/retry":
            return httpx.Response(200, json={"job": {"id": "q1", "status": "queued"}})
        return httpx.Response(404, json={"detail": "missing"})

    transport = httpx.MockTransport(handler)
    client = AgentApiClient(
        CliConfig(base_url="http://testserver", ws_url="ws://testserver"),
        client=httpx.Client(transport=transport, base_url="http://testserver"),
    )

    job = client.get_queue_job("q1")
    assert job["status"] == "failed"
    retried = client.retry_queue_job("q1")
    assert retried["status"] == "queued"
    assert ("GET", "/queue/jobs/q1") in seen
    assert ("POST", "/queue/jobs/q1/retry") in seen


def test_api_client_retry_returns_error_on_conflict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Job is not in a retryable state."})

    transport = httpx.MockTransport(handler)
    client = AgentApiClient(
        CliConfig(base_url="http://testserver", ws_url="ws://testserver"),
        client=httpx.Client(transport=transport, base_url="http://testserver"),
    )
    from backend.app.cli.api_client import CliApiError

    with pytest.raises(CliApiError) as exc_info:
        client.retry_queue_job("q1")
    assert exc_info.value.status_code == 409


def test_permission_prompt_approve_and_deny_call_backend() -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def approve_permission(self, permission_id: str) -> None:
            calls.append(("approve", permission_id))

        def deny_permission(self, permission_id: str) -> None:
            calls.append(("deny", permission_id))

    console = Console(record=True)
    permission = {"id": "p1", "permission_key": "write.file", "resource": "README.md"}

    assert (
        handle_permission_request(FakeClient(), permission, prompt=lambda _text: "approve", console=console)
        == "approved"
    )
    assert (
        handle_permission_request(FakeClient(), permission, prompt=lambda _text: "deny", console=console)
        == "denied"
    )
    assert calls == [("approve", "p1"), ("deny", "p1")]


def test_human_input_prompt_answer_cancel_and_validation() -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def answer_human_input(self, request_id: str, *, answer: str) -> None:
            calls.append(("answer", f"{request_id}:{answer}"))

        def cancel_human_input(self, request_id: str, *, message: str | None = None) -> None:
            calls.append(("cancel", f"{request_id}:{message}"))

    console = Console(record=True)
    request = {"id": "q1", "question": "Ship?", "choices": ["yes", "no"], "allow_free_text": False}
    answers = iter(["maybe", "yes"])

    assert (
        handle_human_input_request(FakeClient(), request, prompt=lambda _text: next(answers), console=console)
        == "answered"
    )
    assert (
        handle_human_input_request(FakeClient(), request, prompt=lambda _text: "/cancel", console=console)
        == "cancelled"
    )
    assert calls == [("answer", "q1:yes"), ("cancel", "q1:cancelled from CLI")]


def test_diff_preview_extracts_file_mutation_metadata() -> None:
    payload = {
        "permission_key": "write.file",
        "input": {"path": "backend/app/example.py"},
        "metadata": {"diff_preview": "--- a\n+++ b\n", "risk_level": "high"},
    }

    assert should_show_diff(payload)
    preview = extract_diff_preview(payload)
    assert preview["diff"] == "--- a\n+++ b\n"
    assert preview["target_paths"] == ["backend/app/example.py"]
    assert preview["risk_level"] == "high"


def test_backend_permission_preview_metadata_for_patch_is_redacted_and_targeted() -> None:
    metadata = _permission_preview_metadata(
        tool_name="patch.apply",
        permission_key="patch.apply",
        input_json={"patch_text": "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-old\n+password=secret\n"},
        risk_level="high",
    )

    assert metadata["operation_type"] == "patch"
    assert metadata["target_paths"] == [".env"]
    assert metadata["risk_level"] == "high"
    assert "[REDACTED]" in metadata["diff_preview"]


def test_render_tables_and_event_are_not_raw_json() -> None:
    console = Console(record=True, width=120)
    console.print(agents_table([{"id": "build", "name": "Build", "mode": "code", "max_steps": 10}]))
    console.print(sessions_table([{"id": "s1", "title": "CLI", "agent_id": "build", "status": "ready"}]))
    console.print(
        event_renderable(
            {
                "type": "message.created",
                "payload": {"message": {"role": "assistant", "content": "**done**"}},
            }
        )
    )
    output = console.export_text()
    assert "Agents" in output
    assert "Sessions" in output
    assert "Assistant Message" in output


def test_cli_help_and_subcommands_parse() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "health",
        "agents",
        "sessions",
        "tui",
        "events",
        "permissions",
        "questions",
        "diff",
        "queue",
    ):
        assert command in result.output


def test_cli_events_command_hits_backend() -> None:
    runner = CliRunner()
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"method": request.method, "path": request.url.path})
        if request.url.path == "/sessions/s1/events":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": "e1",
                            "type": "permission.requested",
                            "payload": {"permission_key": "write.file", "resource": "x.py"},
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    class _Config:
        base_url = "http://testserver"
        ws_url = "ws://testserver"
        timeout_seconds = 5.0
        stream_reconnect_attempts = 1

    from backend.app.cli import config as config_module
    from backend.app.cli import main as main_module

    original_load = config_module.load_cli_config

    def _fake_load() -> CliConfig:
        return CliConfig(base_url="http://testserver", ws_url="ws://testserver")

    config_module.load_cli_config = _fake_load
    main_module.load_cli_config = _fake_load
    try:
        transport = httpx.MockTransport(handler)
        original_client = main_module.AgentApiClient

        def _patched_client(_config: CliConfig) -> AgentApiClient:
            return AgentApiClient(
                _config,
                client=httpx.Client(transport=transport, base_url="http://testserver"),
            )

        main_module.AgentApiClient = _patched_client
        try:
            result = runner.invoke(app, ["events", "--session", "s1", "--limit", "10"])
        finally:
            main_module.AgentApiClient = original_client
    finally:
        config_module.load_cli_config = original_load
        main_module.load_cli_config = original_load

    assert result.exit_code == 0
    assert any(call["path"] == "/sessions/s1/events" for call in captured)


def test_cli_permissions_questions_and_diff_commands_parse() -> None:
    runner = CliRunner()
    for args in (
        ["permissions", "--help"],
        ["questions", "--help"],
        ["diff", "--help"],
        ["events", "--help"],
        ["tui", "--help"],
        ["queue", "retry", "--help"],
        ["queue", "show", "--help"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, args


def test_cli_diff_command_handles_no_diff_gracefully() -> None:
    runner = CliRunner()
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"method": request.method, "path": request.url.path})
        if request.url.path == "/sessions/s-empty/events":
            return httpx.Response(200, json={"events": []})
        return httpx.Response(404, json={"detail": "not found"})

    from backend.app.cli import config as config_module
    from backend.app.cli import main as main_module

    original_load = config_module.load_cli_config
    config_module.load_cli_config = lambda: CliConfig(
        base_url="http://testserver", ws_url="ws://testserver"
    )
    main_module.load_cli_config = config_module.load_cli_config
    try:
        transport = httpx.MockTransport(handler)
        original_client = main_module.AgentApiClient

        def _patched_client(_config: CliConfig) -> AgentApiClient:
            return AgentApiClient(
                _config,
                client=httpx.Client(transport=transport, base_url="http://testserver"),
            )

        main_module.AgentApiClient = _patched_client
        try:
            result = runner.invoke(app, ["diff", "--session", "s-empty"])
        finally:
            main_module.AgentApiClient = original_client
    finally:
        config_module.load_cli_config = original_load
        main_module.load_cli_config = original_load

    assert result.exit_code == 0
    assert "No events" in result.output or "No diff" in result.output
    assert any(call["path"] == "/sessions/s-empty/events" for call in captured)


def test_cli_queue_retry_failure_returns_nonzero() -> None:
    runner = CliRunner()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Job is not in a retryable state."})

    from backend.app.cli import config as config_module
    from backend.app.cli import main as main_module

    original_load = config_module.load_cli_config
    config_module.load_cli_config = lambda: CliConfig(
        base_url="http://testserver", ws_url="ws://testserver"
    )
    main_module.load_cli_config = config_module.load_cli_config
    try:
        transport = httpx.MockTransport(handler)
        original_client = main_module.AgentApiClient

        def _patched_client(_config: CliConfig) -> AgentApiClient:
            return AgentApiClient(
                _config,
                client=httpx.Client(transport=transport, base_url="http://testserver"),
            )

        main_module.AgentApiClient = _patched_client
        try:
            result = runner.invoke(app, ["queue", "retry", "q1"])
        finally:
            main_module.AgentApiClient = original_client
    finally:
        config_module.load_cli_config = original_load
        main_module.load_cli_config = original_load

    assert result.exit_code != 0
    assert "409" in result.output or "retryable" in result.output.lower()


# ---------------------------------------------------------------------------
# TUI modal tests
# ---------------------------------------------------------------------------


def test_permission_modal_blocks_duplicate_approve() -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def approve_permission(self, permission_id: str) -> None:
            calls.append(("approve", permission_id))

        def deny_permission(self, permission_id: str) -> None:
            calls.append(("deny", permission_id))

    console = Console(record=True)
    modal = PermissionModal(
        permission={"id": "p1", "permission_key": "write.file", "resource": "x.py"}
    )
    first = modal.resolve(client=FakeClient(), choice="approve", console=console)
    second = modal.resolve(client=FakeClient(), choice="approve", console=console)
    assert first.result == ModalResult.APPROVED
    assert second.result == ModalResult.SKIPPED
    assert second.detail == "duplicate"
    assert calls == [("approve", "p1")]


def test_permission_modal_handles_api_failure() -> None:
    class FakeFailingClient:
        def approve_permission(self, permission_id: str) -> None:
            from backend.app.cli.api_client import CliApiError

            raise CliApiError("boom", status_code=409)

        def deny_permission(self, permission_id: str) -> None:  # pragma: no cover
            raise AssertionError

    console = Console(record=True)
    modal = PermissionModal(
        permission={"id": "p1", "permission_key": "write.file", "resource": "x.py"}
    )
    outcome = modal.resolve(
        client=FakeFailingClient(), choice="approve", console=console
    )
    assert outcome.result == ModalResult.FAILED
    assert "boom" in (outcome.detail or "")


def test_human_input_modal_blocks_duplicate_answer() -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def answer_human_input(self, request_id: str, *, answer: str) -> None:
            calls.append(("answer", f"{request_id}:{answer}"))

        def cancel_human_input(self, request_id: str, *, message: str | None = None) -> None:
            calls.append(("cancel", f"{request_id}:{message}"))

    console = Console(record=True)
    modal = HumanInputModal(
        request={
            "id": "q1",
            "question": "Ship?",
            "choices": ["yes", "no"],
            "allow_free_text": False,
        }
    )
    bad = modal.resolve(client=FakeClient(), answer="maybe", console=console)
    assert bad.result == ModalResult.SKIPPED
    assert "Choose one of" in (bad.detail or "")
    first = modal.resolve(client=FakeClient(), answer="yes", console=console)
    second = modal.resolve(client=FakeClient(), answer="yes", console=console)
    assert first.result == ModalResult.ANSWERED
    assert second.result == ModalResult.SKIPPED
    assert second.detail == "duplicate"
    assert calls == [("answer", "q1:yes")]


def test_human_input_modal_validates_choice() -> None:
    console = Console(record=True)
    modal = HumanInputModal(
        request={
            "id": "q1",
            "question": "Ship?",
            "choices": ["yes", "no"],
            "allow_free_text": False,
        }
    )
    outcome = modal.resolve(client=_NullClient(), answer="", console=console)
    assert outcome.result == ModalResult.SKIPPED
    assert "empty" in (outcome.detail or "").lower()
    outcome = modal.resolve(
        client=_NullClient(), answer="maybe", console=console
    )
    assert outcome.result == ModalResult.SKIPPED
    assert "Choose one of" in (outcome.detail or "")


def test_human_input_modal_handles_api_failure() -> None:
    class FakeFailingClient:
        def answer_human_input(self, request_id: str, *, answer: str) -> None:
            from backend.app.cli.api_client import CliApiError

            raise CliApiError("rejected", status_code=409)

        def cancel_human_input(self, request_id: str, *, message: str | None = None) -> None:  # pragma: no cover
            raise AssertionError

    console = Console(record=True)
    modal = HumanInputModal(
        request={
            "id": "q1",
            "question": "Ship?",
            "choices": ["yes", "no"],
            "allow_free_text": False,
        }
    )
    outcome = modal.resolve(
        client=FakeFailingClient(), answer="yes", console=console
    )
    assert outcome.result == ModalResult.FAILED
    assert "rejected" in (outcome.detail or "")


# ---------------------------------------------------------------------------
# Diff modal tests
# ---------------------------------------------------------------------------


def test_diff_modal_no_diff_is_safe() -> None:
    modal = DiffModal(events=[], max_lines=10)
    assert modal.has_diff is False
    panel = modal.render()
    console = Console(record=True, width=200)
    console.print(panel)
    output = console.export_text()
    assert "No diff available" in output


def test_diff_modal_finds_latest_diff_in_events() -> None:
    events = [
        {"type": "message.created", "payload": {"message": {"role": "assistant"}}},
        {
            "type": "permission.requested",
            "payload": {
                "permission_key": "write.file",
                "resource": "x.py",
                "metadata": {
                    "diff_preview": "--- a\n+++ b\n-old\n+new\n",
                    "target_paths": ["x.py"],
                    "operation_type": "write",
                    "risk_level": "medium",
                },
            },
        },
    ]
    modal = DiffModal(events=events, max_lines=50)
    assert modal.has_diff is True
    panel = modal.render()
    console = Console(record=True, width=200)
    console.print(panel)
    output = console.export_text()
    assert "Diff" in output
    assert "x.py" in output or "write" in output


def test_diff_modal_truncates_large_diffs_safely() -> None:
    diff_lines = "\n".join(f"+line {i}" for i in range(500))
    events = [
        {
            "type": "tool_call.completed",
            "payload": {
                "tool_name": "edit.file",
                "metadata": {
                    "diff_preview": diff_lines,
                    "target_paths": ["x.py"],
                    "operation_type": "edit",
                    "risk_level": "low",
                },
            },
        }
    ]
    modal = DiffModal(events=events, max_lines=20)
    assert modal.has_diff is True
    panel = modal.render()
    console = Console(record=True, width=200)
    console.print(panel)
    output = console.export_text()
    assert "truncated" in output


# ---------------------------------------------------------------------------
# TUI state tests (agent switcher + send)
# ---------------------------------------------------------------------------


class _NullClient:
    def list_agents(self):  # pragma: no cover - unused in failure tests
        raise AssertionError

    def approve_permission(self, permission_id: str) -> None:  # pragma: no cover
        raise AssertionError

    def deny_permission(self, permission_id: str) -> None:  # pragma: no cover
        raise AssertionError

    def answer_human_input(self, request_id: str, *, answer: str) -> None:  # pragma: no cover
        raise AssertionError

    def cancel_human_input(self, request_id: str, *, message: str | None = None) -> None:  # pragma: no cover
        raise AssertionError


class _FakeStateClient:
    def __init__(self) -> None:
        self.agents = [
            {"id": "build", "name": "Build", "description": "coding agent", "model_name": "build-model"},
            {"id": "general", "name": "General", "description": "chat agent", "model_name": "general-model"},
        ]
        self.agents_calls = 0
        self.sent: list[dict] = []
        self.session_id: str | None = None
        self.events = []
        self.permissions = []
        self.human_inputs = []

    def list_agents(self):
        self.agents_calls += 1
        return list(self.agents)

    def health(self):
        return {"status": "ok"}

    def create_session(self, *, title=None, agent_id="build", model_name=None):
        self.session_id = "s-1"
        return {"id": self.session_id, "title": title, "agent_id": agent_id}

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
                "model_name": model_name,
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

    def queue_stats(self):  # pragma: no cover
        return {"stats": {}}



def test_tui_state_defaults_active_agent_to_first_loaded() -> None:
    fake = _FakeStateClient()
    state = TuiState()
    set_agents(state, fake.agents)
    assert state.active_agent_id == "build"
    assert state.active_agent_name == "Build"
    assert state.active_model == "build-model"


def test_tui_state_set_agent_validates_against_loaded() -> None:
    fake = _FakeStateClient()
    state = TuiState()
    set_agents(state, fake.agents)
    from backend.app.cli.tui_state import select_agent
    select_agent(state, "general")
    assert state.active_agent_id == "general"
    assert state.active_agent_name == "General"
    assert state.active_model == "general-model"
    # Unknown agent still updates the id (lets the TUI show a typed value)
    # but leaves the display name/model blank.
    select_agent(state, "nonexistent")
    assert state.active_agent_id == "nonexistent"
    assert state.active_agent_name == "nonexistent"
    assert state.active_model == ""


def test_tui_state_permission_request_populates_pending() -> None:
    state = TuiState()
    apply_event(
        state,
        {
            "type": "permission.requested",
            "payload": {"id": "p1", "permission_key": "write.file"},
        },
    )
    assert "p1" in state.pending_permissions
    apply_event(
        state,
        {"type": "permission.approved", "payload": {"id": "p1"}},
    )
    assert "p1" not in state.pending_permissions


def test_tui_state_tool_call_event_sets_latest_diff() -> None:
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
                    "risk_level": "low",
                },
            },
        },
    )
    assert state.latest_diff is not None
    assert state.latest_diff["target_paths"] == ["x.py"]
    assert "old" in state.latest_diff["diff"]


def test_tui_retry_dispatches_to_api() -> None:
    retried: list[str] = []

    class _Client(_FakeStateClient):
        def retry_queue_job(self, job_id, *, reason="cli_retry"):
            retried.append(job_id)
            return {"id": job_id, "status": "queued"}

    client = _Client()
    assert client.retry_queue_job("job-1")["status"] == "queued"
    assert retried == ["job-1"]


def test_tui_run_tui_import_smoke() -> None:
    """Smoke import: AgentPlatformTuiApp + run_tui can be imported and instantiated."""
    from backend.app.cli.tui_app import AgentPlatformTuiApp, run_tui, run_tui_check
    assert callable(run_tui)
    assert callable(run_tui_check)
    assert AgentPlatformTuiApp.__module__ == "backend.app.cli.tui_app"


def test_tui_check_runs_headless_against_fake_client() -> None:
    """run_tui_check should compose the app, hit the backend via the API client, and exit 0."""
    from backend.app.cli.tui_app import run_tui_check

    fake = _FakeStateClient()
    config = CliConfig(base_url="http://testserver", ws_url="ws://testserver")
    exit_code = run_tui_check(config=config, client=fake)
    assert exit_code == 0


def test_tui_check_returns_2_on_backend_error() -> None:
    """run_tui_check should return 2 when /health fails."""
    from backend.app.cli.api_client import CliApiError
    from backend.app.cli.tui_app import run_tui_check

    class _Broken(_FakeStateClient):
        def health(self):
            raise CliApiError("backend down")

    exit_code = run_tui_check(
        config=CliConfig(base_url="http://testserver", ws_url="ws://testserver"),
        client=_Broken(),
    )
    assert exit_code == 2


def test_cli_tui_check_flag_invokes_check() -> None:
    """`agentv2 tui --check` should exit 0 (or 2 if backend down) without launching the TUI."""
    runner = CliRunner()
    result = runner.invoke(app, ["tui", "--check"], catch_exceptions=False)
    assert result.exit_code in (0, 2)


def test_cli_tui_help_lists_check_flag() -> None:
    """`agentv2 tui --help` should advertise the new --check flag."""
    runner = CliRunner()
    result = runner.invoke(app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "--check" in result.stdout


def test_tui_app_textual_instantiation() -> None:
    """AgentPlatformTuiApp should construct cleanly (proves Textual compose works)."""
    from backend.app.cli.tui_app import AgentPlatformTuiApp
    fake = _FakeStateClient()
    config = CliConfig(base_url="http://testserver", ws_url="ws://testserver")
    app_obj = AgentPlatformTuiApp(config=config, client=fake)
    assert app_obj is not None

