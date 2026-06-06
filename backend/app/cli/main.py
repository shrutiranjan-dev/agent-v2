from __future__ import annotations

import subprocess
from typing import Any

import typer
import uvicorn
from rich.console import Console

from backend.app.cli.api_client import AgentApiClient, CliApiError
from backend.app.cli.config import load_cli_config
from backend.app.cli.render import (
    agents_table,
    artifacts_table,
    events_table,
    queue_jobs_table,
    render_error,
    render_health,
    sessions_table,
)
from backend.app.cli.session_commands import run_chat_stream
from backend.app.cli.tui_app import run_tui
from backend.app.cli.tui_modals import DiffModal
from backend.app.cli.websocket_client import SessionEventStream
from backend.app.core.config import get_settings

app = typer.Typer(help="Local Agent Platform CLI")
sessions_app = typer.Typer(help="Session commands")
queue_app = typer.Typer(help="Queue commands")
artifacts_app = typer.Typer(help="Artifact commands")
app.add_typer(sessions_app, name="sessions")
app.add_typer(queue_app, name="queue")
app.add_typer(artifacts_app, name="artifacts")
console = Console()


@app.command()
def serve() -> None:
    """Run the FastAPI backend locally with Uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "backend.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.env == "development",
    )


@app.command()
def migrate() -> None:
    """Apply the latest Alembic migrations against the configured database."""
    subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)


@app.command()
def health() -> None:
    """Print backend health status."""
    with _client() as client:
        console.print(render_health(client.health()))


@app.command()
def agents() -> None:
    """List all available agents from the backend."""
    with _client() as client:
        console.print(agents_table(client.list_agents()))


@sessions_app.command("list")
def sessions_list() -> None:
    """List all sessions visible to the current operator."""
    with _client() as client:
        console.print(sessions_table(client.list_sessions()))


@sessions_app.command("create")
def sessions_create(
    title: str = typer.Option("Terminal session", "--title", "-t", help="Human-friendly session title."),
    agent: str = typer.Option("build", "--agent", "-a", help="Agent id used for this session."),
    model: str | None = typer.Option(None, "--model", help="Optional model name override."),
) -> None:
    """Create a new session and print its id."""
    with _client() as client:
        session = client.create_session(title=title, agent_id=agent, model_name=model)
        console.print(sessions_table([session]))


@sessions_app.command("show")
def sessions_show(session_id: str) -> None:
    """Show a single session with recent messages."""
    with _client() as client:
        detail = client.get_session(session_id)
        console.print(sessions_table([detail["session"]]))
        for message in detail.get("messages", []):
            console.print(f"[bold]{message.get('role')}[/bold]: {message.get('content')}")


@app.command(name="events")
def events_cmd(
    session: str = typer.Option(..., "--session", "-s", help="Session id to read events for."),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of events to display."),
) -> None:
    """Print recent system events for a session."""
    with _client() as client:
        events = client.list_events(session)
        if limit > 0:
            events = events[-limit:]
        console.print(events_table(events))


@app.command(name="permissions")
def permissions_cmd(
    session: str = typer.Option(..., "--session", "-s", help="Session id to read permissions for."),
) -> None:
    """Print pending permission requests for a session."""
    with _client() as client:
        rows = client.list_permissions(session_id=session)
        console.print(events_table(_permission_rows(rows)))


@app.command(name="questions")
def questions_cmd(
    session: str = typer.Option(..., "--session", "-s", help="Session id to read human-input requests for."),
) -> None:
    """Print pending human-input (question) requests for a session."""
    with _client() as client:
        rows = client.list_human_input_requests(session_id=session)
        console.print(events_table(_human_input_rows(rows)))


@app.command(name="diff")
def diff_cmd(
    session: str = typer.Option(..., "--session", "-s", help="Session id to read the latest diff for."),
    max_lines: int = typer.Option(200, "--max-lines", help="Maximum number of diff lines to display."),
) -> None:
    """Print the latest diff for a session based on recorded events."""
    with _client() as client:
        events = client.list_events(session)
        if not events:
            console.print("[yellow]No events recorded for this session yet.[/yellow]")
            return
        diff = DiffModal(events=events, max_lines=max_lines)
        if not diff._latest:
            console.print(
                "[yellow]No diff available for this session yet. "
                "Trigger a write.file, edit.file, or patch.apply to see one.[/yellow]"
            )
            return
        console.print(diff.render())


@queue_app.command("status")
def queue_status(session: str | None = typer.Option(None, "--session", "-s")) -> None:
    """Print queue stats and recent jobs."""
    with _client() as client:
        console.print(client.queue_stats())
        console.print(queue_jobs_table(client.list_queue_jobs(session_id=session)))


@queue_app.command("retry")
def queue_retry(
    job: str = typer.Argument(..., help="Queue job id to retry."),
    reason: str = typer.Option("cli_retry", "--reason", "-r", help="Reason recorded for the retry."),
) -> None:
    """Retry a failed/dead-lettered/cancelled queue job.

    Returns non-zero if the job cannot be retried in its current state.
    """
    with _client() as client:
        try:
            row = client.retry_queue_job(job, reason=reason)
        except CliApiError as exc:
            console.print(render_error(exc))
            raise typer.Exit(code=1) from exc
        console.print(queue_jobs_table([row]))


@queue_app.command("show")
def queue_show(
    job: str = typer.Argument(..., help="Queue job id to inspect."),
) -> None:
    """Print a single queue job by id."""
    with _client() as client:
        try:
            row = client.get_queue_job(job)
        except CliApiError as exc:
            console.print(render_error(exc))
            raise typer.Exit(code=1) from exc
        console.print(queue_jobs_table([row]))


@artifacts_app.command("list")
def artifacts_list(session: str | None = typer.Option(None, "--session", "-s")) -> None:
    """List artifacts, optionally filtered by session id."""
    with _client() as client:
        console.print(artifacts_table(client.list_artifacts(session_id=session)))


@app.command()
def chat(
    prompt: str | None = typer.Argument(None),
    session: str | None = typer.Option(None, "--session", "-s", help="Existing session id to use."),
    agent: str = typer.Option("build", "--agent", "-a", help="Agent id used for new sessions."),
    model: str | None = typer.Option(None, "--model", help="Optional model name override."),
    title: str = typer.Option("Terminal session", "--title", help="Title used when creating a new session."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Skip streaming events after sending."),
    yes: bool = typer.Option(False, "--yes", help="Do not prompt for permissions or human input."),
) -> None:
    """Send a single prompt and stream session events."""
    content = prompt or typer.prompt("Prompt")
    config = load_cli_config()
    with AgentApiClient(config) as client:
        active_session = session
        if not active_session:
            created = client.create_session(title=title, agent_id=agent, model_name=model)
            active_session = str(created["id"])
            console.print(f"[green]Created session {active_session}[/green]")
        response = client.send_message(active_session, content=content, agent_id=agent, model_name=model)
        run = response.get("agent_run", {})
        console.print(f"[cyan]Run {run.get('id')} status={run.get('status')}[/cyan]")
        if no_stream:
            return
        run_chat_stream(
            client=client,
            stream=SessionEventStream(config, active_session),
            console=console,
            interactive=not yes,
        )


@app.command()
def tui() -> None:
    """Start the keyboard-driven Rich TUI for sessions, agents, and queue jobs."""
    with _client() as client:
        run_tui(client, console=console)


def _client() -> AgentApiClient:
    return AgentApiClient(load_cli_config())


def main() -> None:
    try:
        app()
    except CliApiError as exc:
        console.print(render_error(exc))
        raise typer.Exit(code=1) from exc


def _permission_rows(permissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for perm in permissions:
        metadata = perm.get("metadata") if isinstance(perm.get("metadata"), dict) else {}
        rows.append(
            {
                "id": str(
                    perm.get("id")
                    or perm.get("permission_request_id")
                    or ""
                ),
                "type": "permission.requested",
                "status": str(perm.get("status", "pending")),
                "resource": str(perm.get("resource", "")),
                "risk_level": str(metadata.get("risk_level", "")),
            }
        )
    return rows


def _human_input_rows(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for req in requests:
        rows.append(
            {
                "id": str(
                    req.get("id") or req.get("human_input_request_id") or ""
                ),
                "type": "question.requested",
                "status": str(req.get("status", "pending")),
                "question": str(req.get("question", "")),
            }
        )
    return rows


if __name__ == "__main__":
    main()
