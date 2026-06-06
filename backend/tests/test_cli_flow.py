from __future__ import annotations

import json

import httpx
from rich.console import Console
from typer.testing import CliRunner

from backend.app.cli.api_client import AgentApiClient
from backend.app.cli.config import CliConfig
from backend.app.cli.diff_preview import extract_diff_preview, should_show_diff
from backend.app.cli.main import app
from backend.app.cli.render import agents_table, event_renderable, sessions_table
from backend.app.cli.session_commands import handle_human_input_request, handle_permission_request
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
    assert "health" in result.output
    assert "sessions" in result.output
    assert "tui" in result.output
