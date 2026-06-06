from __future__ import annotations

import subprocess

import typer
import uvicorn
from rich.console import Console

from backend.app.cli.api_client import AgentApiClient, CliApiError
from backend.app.cli.config import load_cli_config
from backend.app.cli.render import (
    agents_table,
    artifacts_table,
    queue_jobs_table,
    render_error,
    render_health,
    sessions_table,
)
from backend.app.cli.session_commands import run_chat_stream
from backend.app.cli.tui_app import run_tui
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
    settings = get_settings()
    uvicorn.run(
        "backend.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.env == "development",
    )


@app.command()
def migrate() -> None:
    subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)


@app.command()
def health() -> None:
    with _client() as client:
        console.print(render_health(client.health()))


@app.command()
def agents() -> None:
    with _client() as client:
        console.print(agents_table(client.list_agents()))


@sessions_app.command("list")
def sessions_list() -> None:
    with _client() as client:
        console.print(sessions_table(client.list_sessions()))


@sessions_app.command("create")
def sessions_create(
    title: str = typer.Option("Terminal session", "--title", "-t"),
    agent: str = typer.Option("build", "--agent", "-a"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    with _client() as client:
        session = client.create_session(title=title, agent_id=agent, model_name=model)
        console.print(sessions_table([session]))


@sessions_app.command("show")
def sessions_show(session_id: str) -> None:
    with _client() as client:
        detail = client.get_session(session_id)
        console.print(sessions_table([detail["session"]]))
        for message in detail.get("messages", []):
            console.print(f"[bold]{message.get('role')}[/bold]: {message.get('content')}")


@queue_app.command("status")
def queue_status(session: str | None = typer.Option(None, "--session")) -> None:
    with _client() as client:
        console.print(client.queue_stats())
        console.print(queue_jobs_table(client.list_queue_jobs(session_id=session)))


@artifacts_app.command("list")
def artifacts_list(session: str | None = typer.Option(None, "--session")) -> None:
    with _client() as client:
        console.print(artifacts_table(client.list_artifacts(session_id=session)))


@app.command()
def chat(
    prompt: str | None = typer.Argument(None),
    session: str | None = typer.Option(None, "--session", "-s"),
    agent: str = typer.Option("build", "--agent", "-a"),
    model: str | None = typer.Option(None, "--model"),
    title: str = typer.Option("Terminal session", "--title"),
    no_stream: bool = typer.Option(False, "--no-stream"),
    yes: bool = typer.Option(False, "--yes", help="Do not prompt for permissions or human input."),
) -> None:
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


if __name__ == "__main__":
    main()
