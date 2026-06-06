from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from backend.app.cli.api_client import AgentApiClient
from backend.app.cli.render import agents_table, queue_jobs_table, sessions_table


def run_tui(client: AgentApiClient, *, console: Console | None = None) -> None:
    console = console or Console()
    agent_id = "build"
    session_id: str | None = None
    console.print("[bold]Agent Platform Terminal[/bold]")
    console.print("Commands: new, sessions, agents, use <id>, agent <id>, send <prompt>, status, quit")
    while True:
        command = Prompt.ask("[cyan]agentv2[/cyan]").strip()
        if command in {"q", "quit", "exit"}:
            return
        if command in {"sessions", "s"}:
            console.print(sessions_table(client.list_sessions()))
            continue
        if command in {"agents", "a"}:
            console.print(agents_table(client.list_agents()))
            continue
        if command == "new":
            title = Prompt.ask("Title", default="Terminal session")
            session = client.create_session(title=title, agent_id=agent_id)
            session_id = str(session["id"])
            console.print(f"[green]Created session {session_id}[/green]")
            continue
        if command.startswith("use "):
            session_id = command.removeprefix("use ").strip()
            detail = client.get_session(session_id)
            console.print(Panel(str(detail["session"].get("title", session_id)), title="Active Session"))
            continue
        if command.startswith("agent "):
            agent_id = command.removeprefix("agent ").strip()
            console.print(f"[green]Agent set to {agent_id}[/green]")
            continue
        if command == "status":
            _render_status(client, console=console, session_id=session_id)
            continue
        if command.startswith("send "):
            if not session_id:
                session = client.create_session(title="Terminal session", agent_id=agent_id)
                session_id = str(session["id"])
                console.print(f"[green]Created session {session_id}[/green]")
            prompt = command.removeprefix("send ").strip()
            with Live(Panel("Sending prompt...", title="Run"), console=console, transient=True):
                response = client.send_message(session_id, content=prompt, agent_id=agent_id)
            run = response.get("agent_run", {})
            console.print(Panel(f"Run {run.get('id')} -> {run.get('status')}", title="Queued"))
            continue
        console.print("[yellow]Unknown command. Try sessions, new, agents, send <prompt>, status, quit.[/yellow]")


def _render_status(client: AgentApiClient, *, console: Console, session_id: str | None) -> None:
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    sessions = client.list_sessions()
    jobs = client.list_queue_jobs(session_id=session_id, limit=20)
    grid.add_row(sessions_table(sessions), queue_jobs_table(jobs))
    console.print(grid)
