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
    file_change_detail_panel,
    file_changes_table,
    queue_jobs_table,
    render_error,
    render_health,
    sessions_table,
)
from backend.app.cli.session_commands import run_chat_stream
from backend.app.cli.tui_app import run_tui, run_tui_check
from backend.app.cli.tui_modals import DiffModal
from backend.app.cli.websocket_client import SessionEventStream
from backend.app.core.config import get_settings

app = typer.Typer(help="Local Agent Platform CLI")
sessions_app = typer.Typer(help="Session commands")
queue_app = typer.Typer(help="Queue commands")
artifacts_app = typer.Typer(help="Artifact commands")
changes_app = typer.Typer(help="File change commands")
app.add_typer(sessions_app, name="sessions")
app.add_typer(queue_app, name="queue")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(changes_app, name="changes")
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


@changes_app.command("list")
def changes_list(
    session: str | None = typer.Option(None, "--session", "-s", help="Filter by session id."),
    run: str | None = typer.Option(None, "--run", "-r", help="Filter by agent run id."),
    path: str | None = typer.Option(None, "--path", "-p", help="Filter by exact relative path."),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of file changes to display."),
) -> None:
    """List durable file changes recorded for write/edit/patch tool calls."""
    with _client() as client:
        rows = client.list_file_changes(session_id=session, run_id=run, path=path, limit=limit)
        if not rows:
            console.print("[yellow]No file changes recorded yet.[/yellow]")
            return
        console.print(file_changes_table(rows))


@changes_app.command("show")
def changes_show(file_change_id: str) -> None:
    """Show a single file change with its diff."""
    with _client() as client:
        try:
            row = client.get_file_change(file_change_id, include_content=True)
        except CliApiError as exc:
            console.print(render_error(exc))
            raise typer.Exit(code=1) from exc
        if not row:
            console.print(f"[red]File change {file_change_id} not found.[/red]")
            raise typer.Exit(code=1)
        console.print(file_change_detail_panel(row))


@changes_app.command("revert")
def changes_revert(
    file_change_id: str = typer.Argument(..., help="File change id to revert."),
    force: bool = typer.Option(False, "--force", help="Allow revert for secret-like files and skip hash check."),
    permission_request_id: str | None = typer.Option(
        None,
        "--permission-request-id",
        help="Approved permission request id; required when the server returns 202 waiting_permission.",
    ),
    approve_waiting: bool = typer.Option(
        False,
        "--approve",
        help="Auto-approve a waiting_permission response and retry the revert.",
    ),
) -> None:
    """Revert a recorded file change, restoring the prior content when possible.

    If the server requires approval, the request returns 202 with a
    ``permission_request_id``. Pass ``--approve`` to auto-approve the
    pending request and retry the revert with the new id; otherwise the
    permission id is printed so the operator can approve it separately
    via ``agentv2 permissions ...``.
    """
    with _client() as client:
        try:
            row = client.revert_file_change(
                file_change_id,
                force=force,
                permission_request_id=permission_request_id,
            )
        except CliApiError as exc:
            if exc.status_code == 202 and approve_waiting:
                permission_id = _extract_permission_request_id(str(exc))
                if not permission_id:
                    console.print(render_error(exc))
                    raise typer.Exit(code=1) from exc
                console.print(f"[yellow]Revert requires approval; approving {permission_id}...[/yellow]")
                try:
                    client.approve_permission(permission_id, message="cli_approval")
                except CliApiError as approve_exc:
                    console.print(render_error(approve_exc))
                    raise typer.Exit(code=1) from approve_exc
                try:
                    row = client.revert_file_change(
                        file_change_id,
                        force=force,
                        permission_request_id=permission_id,
                    )
                except CliApiError as retry_exc:
                    console.print(render_error(retry_exc))
                    raise typer.Exit(code=1) from retry_exc
            else:
                if exc.status_code == 202:
                    permission_id = _extract_permission_request_id(str(exc))
                    if permission_id:
                        console.print(
                            f"[yellow]Revert is waiting for approval "
                            f"(permission_request_id={permission_id}).[/yellow]"
                        )
                        console.print(
                            f"Approve with: [cyan]agentv2 permissions approve {permission_id}[/cyan] "
                            f"or retry with [cyan]--permission-request-id {permission_id}[/cyan]."
                        )
                        raise typer.Exit(code=2) from exc
                console.print(render_error(exc))
                raise typer.Exit(code=1) from exc
        if not row:
            console.print(f"[red]File change {file_change_id} not found.[/red]")
            raise typer.Exit(code=1)
        console.print(file_change_detail_panel(row))
        if row.get("revert_status") != "reverted":
            console.print(
                f"[yellow]Revert reported status={row.get('revert_status')}; "
                f"check revert_error for details.[/yellow]"
            )


@changes_app.command("revert-batch")
def changes_revert_batch(
    file_change_ids: list[str] = typer.Argument(..., help="File change ids to revert (space separated)."),
    force: bool = typer.Option(False, "--force", help="Allow revert for secret-like files and skip hash check."),
    permission_request_id: str | None = typer.Option(
        None,
        "--permission-request-id",
        help="Approved permission request id; required when the server returns 202 waiting_permission.",
    ),
) -> None:
    """Revert multiple file changes atomically (validate-all-before-apply)."""
    with _client() as client:
        try:
            result = client.revert_file_changes_batch(
                file_change_ids,
                force=force,
                permission_request_id=permission_request_id,
            )
        except CliApiError as exc:
            if exc.status_code == 202:
                permission_id = _extract_permission_request_id(str(exc))
                if permission_id:
                    console.print(
                        f"[yellow]Batch revert is waiting for approval "
                        f"(permission_request_id={permission_id}).[/yellow]"
                    )
                    console.print(
                        f"Approve with: [cyan]agentv2 permissions approve {permission_id}[/cyan] "
                        f"or retry with [cyan]--permission-request-id {permission_id}[/cyan]."
                    )
                    raise typer.Exit(code=2) from exc
            console.print(render_error(exc))
            raise typer.Exit(code=1) from exc
        reverted = result.get("reverted") or []
        skipped = result.get("skipped") or []
        failed = result.get("failed") or []
        console.print(
            f"[green]Batch revert ok: reverted={len(reverted)} skipped={len(skipped)} "
            f"failed={len(failed)} restored_from_snapshots={result.get('restored_from_snapshots', False)}[/green]"
        )
        for entry in skipped:
            console.print(
                f"[yellow]SKIP {entry.get('change_id', '?')} ({entry.get('reason', '?')}): "
                f"{entry.get('error', '')}[/yellow]"
            )
        for entry in failed:
            console.print(
                f"[red]FAIL {entry.get('change_id', '?')} ({entry.get('reason', '?')}): "
                f"{entry.get('error', '')}[/red]"
            )


def _extract_permission_request_id(message: str) -> str | None:
    import re

    match = re.search(
        r"permission_request_id[\"']?\s*[:=]\s*[\"']?([0-9a-fA-F-]{36})",
        message,
    )
    if match:
        return match.group(1)
    return None


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
def tui(
    check: bool = typer.Option(
        False,
        "--check",
        help="Run a non-interactive TUI smoke (loads agents/sessions, prints a status line, exits).",
    ),
) -> None:
    """Start the keyboard-driven Textual TUI for sessions, agents, and queue jobs."""
    if check:
        raise typer.Exit(code=run_tui_check())
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
