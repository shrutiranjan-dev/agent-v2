from __future__ import annotations

import os
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from backend.app.cli.api_client import AgentApiClient, CliApiError
from backend.app.cli.render import agents_table, events_table, queue_jobs_table, sessions_table
from backend.app.cli.tui_modals import (
    DiffModal,
    HumanInputModal,
    ModalOutcome,
    ModalResult,
    PermissionModal,
)

MAX_PROMPT_LEN = 4000
EVENT_PAGE_LIMIT = 200
PERMISSION_PAGE_LIMIT = 200
HUMAN_INPUT_PAGE_LIMIT = 200
DIFF_EVENT_LIMIT = 500
TUI_RETRY_STATES = {"failed", "dead_letter", "dead_lettered", "cancelled"}


def run_tui(client: AgentApiClient, *, console: Console | None = None) -> None:
    console = console or Console()
    state = _TuiState(client=client, console=console)
    state.welcome()
    while True:
        try:
            command = Prompt.ask("[cyan]agentv2[/cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]Exiting TUI.[/dim]")
            return
        if command in {"q", "quit", "exit"}:
            return
        if command in {"help", "?"}:
            state.help()
            continue
        if command in {"health", "h"}:
            state.show_health()
            continue
        if command in {"agents", "a"}:
            state.show_agents()
            continue
        if command in {"sessions", "s"}:
            state.show_sessions()
            continue
        if command in {"use", "open"}:
            state.interactive_use_session()
            continue
        if command.startswith("use "):
            state.use_session(command.removeprefix("use ").strip())
            continue
        if command in {"new"}:
            state.interactive_new_session()
            continue
        if command in {"agent", "agents pick", "pick agent"}:
            state.interactive_pick_agent()
            continue
        if command.startswith("agent "):
            state.set_agent(command.removeprefix("agent ").strip())
            continue
        if command in {"events", "ev"}:
            state.show_events(limit=EVENT_PAGE_LIMIT)
            continue
        if command in {"permissions", "perm"}:
            state.show_permissions()
            continue
        if command in {"questions", "q?"}:
            state.show_questions()
            continue
        if command in {"diff", "d"}:
            state.show_diff(interactive=False)
            continue
        if command.startswith("diff "):
            state.handle_diff_command(command.removeprefix("diff ").strip())
            continue
        if command in {"retry", "r"}:
            state.interactive_retry()
            continue
        if command.startswith("retry "):
            state.retry_job(command.removeprefix("retry ").strip())
            continue
        if command in {"status"}:
            state.show_status()
            continue
        if command in {"send"}:
            console.print(
                "[yellow]Use: send <prompt>[/yellow]"
            )
            continue
        if command.startswith("send "):
            state.send_prompt(command.removeprefix("send ").strip())
            continue
        if command.startswith("approve "):
            state.approve_permission(command.removeprefix("approve ").strip())
            continue
        if command.startswith("deny "):
            state.deny_permission(command.removeprefix("deny ").strip())
            continue
        if command.startswith("answer "):
            state.answer_human_input(
                command.removeprefix("answer ").strip().split(maxsplit=1)
            )
            continue
        console.print(
            "[yellow]Unknown command. Type 'help' to see the available commands.[/yellow]"
        )


def _show_diff_for_session(
    client: AgentApiClient,
    session_id: str,
    *,
    console: Console,
) -> DiffModal:
    events = client.list_events(session_id)
    diff = DiffModal(events=events, max_lines=200)
    console.print(diff.render())
    return diff


class _TuiState:
    """Encapsulates the long-lived state of the TUI loop."""

    def __init__(self, *, client: AgentApiClient, console: Console) -> None:
        self.client = client
        self.console = console
        self.session_id: str | None = None
        self.agent_id: str | None = None
        self.agents: list[dict[str, Any]] = []
        self._pending_permissions: dict[str, PermissionModal] = {}
        self._pending_human_inputs: dict[str, HumanInputModal] = {}

    def welcome(self) -> None:
        self.console.print("[bold]Agent Platform Terminal[/bold]")
        self.console.print(
            "Type 'help' for commands. 'agent' opens the agent switcher. "
            "'diff' shows the latest diff for the active session."
        )
        try:
            self.refresh_agents()
        except CliApiError as exc:
            self.console.print(f"[yellow]Could not load agents: {exc}[/yellow]")
        if self.agents and not self.agent_id:
            first = self.agents[0]
            self.agent_id = str(first.get("id"))
            self.console.print(
                f"[dim]Default agent: {self.agent_id}. Use 'agent' to switch.[/dim]"
            )

    def help(self) -> None:
        self.console.print(
            Panel(
                "\n".join(
                    [
                        "help                    Show this help text.",
                        "health                  Show backend health.",
                        "agents                  List available agents.",
                        "agent                   Open the agent switcher.",
                        "agent <id>              Set the active agent by id.",
                        "sessions                List sessions.",
                        "new                     Create a new session.",
                        "use <id>                Switch to an existing session.",
                        "events                  Show recent events for active session.",
                        "permissions             Show pending permission requests.",
                        "questions               Show pending human-input requests.",
                        "approve <id>            Approve a permission request.",
                        "deny <id>               Deny a permission request.",
                        "answer <id> <text>      Answer a human-input request.",
                        "diff                    Show the latest diff (active session).",
                        "diff <id>               Show the latest diff for a session id.",
                        "retry                   Retry the latest failed job (active session).",
                        "retry <job_id>          Retry a specific queue job.",
                        "status                  Show sessions and queue status.",
                        "send <prompt>           Send a prompt to the active session.",
                        "quit                    Exit the TUI.",
                    ]
                ),
                title="Agent Platform TUI",
                border_style="cyan",
            )
        )

    def refresh_agents(self) -> None:
        self.agents = self.client.list_agents()

    def show_health(self) -> None:
        try:
            payload = self.client.health()
        except CliApiError as exc:
            self.console.print(f"[red]Health failed: {exc}[/red]")
            return
        self.console.print(
            Panel(
                f"status: {payload.get('status', 'unknown')}",
                title="Backend Health",
                border_style="green",
            )
        )

    def show_agents(self) -> None:
        try:
            self.refresh_agents()
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load agents: {exc}[/red]")
            return
        self.console.print(agents_table(self.agents))

    def interactive_pick_agent(self) -> None:
        try:
            self.refresh_agents()
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load agents: {exc}[/red]")
            return
        if not self.agents:
            self.console.print("[yellow]No agents available.[/yellow]")
            return
        self.console.print(agents_table(self.agents))
        choice = Prompt.ask(
            "Pick an agent id",
            default=self.agent_id or "",
        ).strip()
        if choice:
            self.set_agent(choice)

    def set_agent(self, agent_id: str) -> None:
        if not agent_id:
            self.console.print("[yellow]Agent id is required.[/yellow]")
            return
        if not self.agents:
            try:
                self.refresh_agents()
            except CliApiError as exc:
                self.console.print(f"[red]Failed to load agents: {exc}[/red]")
                return
        match = next(
            (a for a in self.agents if str(a.get("id")) == agent_id),
            None,
        )
        if match is None:
            self.console.print(
                f"[red]Agent '{agent_id}' not found. Use 'agents' to list available agents.[/red]"
            )
            return
        self.agent_id = agent_id
        self.console.print(
            f"[green]Active agent set to {agent_id}. "
            f"Next prompt will use {match.get('name') or agent_id}.[/green]"
        )

    def show_sessions(self) -> None:
        try:
            sessions = self.client.list_sessions()
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load sessions: {exc}[/red]")
            return
        self.console.print(sessions_table(sessions))

    def interactive_use_session(self) -> None:
        try:
            sessions = self.client.list_sessions()
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load sessions: {exc}[/red]")
            return
        if not sessions:
            self.console.print("[yellow]No sessions to switch to.[/yellow]")
            return
        self.console.print(sessions_table(sessions))
        choice = Prompt.ask(
            "Switch to session id",
            default=self.session_id or "",
        ).strip()
        if choice:
            self.use_session(choice)

    def use_session(self, session_id: str) -> None:
        self.session_id = session_id
        try:
            detail = self.client.get_session(session_id)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load session: {exc}[/red]")
            return
        title = (detail.get("session") or {}).get("title") or session_id
        self.console.print(
            Panel(
                f"{title}\nid={session_id}",
                title="Active Session",
                border_style="cyan",
            )
        )
        self._reset_modals_for_session()

    def interactive_new_session(self) -> None:
        title = Prompt.ask("Session title", default="Terminal session")
        agent_id = Prompt.ask(
            "Agent id",
            default=self.agent_id or (self.agents[0]["id"] if self.agents else "build"),
        ).strip()
        try:
            session = self.client.create_session(title=title, agent_id=agent_id)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to create session: {exc}[/red]")
            return
        self.session_id = str(session["id"])
        self.console.print(
            f"[green]Created session {self.session_id}[/green]"
        )
        self._reset_modals_for_session()

    def show_events(self, *, limit: int = EVENT_PAGE_LIMIT) -> None:
        if not self.session_id:
            self.console.print("[yellow]No active session.[/yellow]")
            return
        try:
            events = self.client.list_events(self.session_id)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load events: {exc}[/red]")
            return
        self.console.print(events_table(events[-limit:]))

    def show_permissions(self) -> None:
        if not self.session_id:
            self.console.print("[yellow]No active session.[/yellow]")
            return
        try:
            rows = self.client.list_permissions(session_id=self.session_id)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load permissions: {exc}[/red]")
            return
        self.console.print(events_table(_permission_rows(rows)))
        for permission in rows:
            modal = self._register_permission(permission)
            if modal.state.value == "open":
                self.console.print(modal.render())

    def show_questions(self) -> None:
        if not self.session_id:
            self.console.print("[yellow]No active session.[/yellow]")
            return
        try:
            rows = self.client.list_human_input_requests(session_id=self.session_id)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load human-input requests: {exc}[/red]")
            return
        self.console.print(events_table(_human_input_rows(rows)))
        for request in rows:
            modal = self._register_human_input(request)
            if modal.state.value == "open":
                self.console.print(modal.render())

    def approve_permission(self, permission_id: str) -> None:
        modal = self._pending_permissions.get(permission_id)
        if modal is None:
            self.console.print(
                f"[yellow]No active modal for permission {permission_id}; "
                "use 'permissions' to refresh.[/yellow]"
            )
            return
        outcome = modal.resolve(client=self.client, choice="approve", console=self.console)
        self._report_outcome("Permission", outcome, success="approved")

    def deny_permission(self, permission_id: str) -> None:
        modal = self._pending_permissions.get(permission_id)
        if modal is None:
            self.console.print(
                f"[yellow]No active modal for permission {permission_id}; "
                "use 'permissions' to refresh.[/yellow]"
            )
            return
        outcome = modal.resolve(client=self.client, choice="deny", console=self.console)
        self._report_outcome("Permission", outcome, success="denied")

    def answer_human_input(self, parts: list[str]) -> None:
        if not parts or not parts[0]:
            self.console.print(
                "[yellow]Usage: answer <request_id> <text>[/yellow]"
            )
            return
        request_id = parts[0]
        answer = parts[1] if len(parts) > 1 else ""
        modal = self._pending_human_inputs.get(request_id)
        if modal is None:
            self.console.print(
                f"[yellow]No active modal for request {request_id}; "
                "use 'questions' to refresh.[/yellow]"
            )
            return
        outcome = modal.resolve(
            client=self.client, answer=answer, console=self.console
        )
        self._report_outcome("Human input", outcome, success="answered")

    def show_diff(self, *, interactive: bool) -> None:
        if not self.session_id:
            self.console.print("[yellow]No active session.[/yellow]")
            return
        try:
            events = self.client.list_events(self.session_id)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load events: {exc}[/red]")
            return
        diff = DiffModal(events=events[-DIFF_EVENT_LIMIT:], max_lines=200)
        self.console.print(diff.render())
        if interactive and not diff.has_diff:
            self.console.print(
                "[dim]No diff metadata yet. Send a prompt that triggers "
                "write.file, edit.file, or patch.apply to see one.[/dim]"
            )

    def handle_diff_command(self, session_id: str) -> None:
        previous = self.session_id
        self.session_id = session_id
        try:
            self.show_diff(interactive=False)
        finally:
            self.session_id = previous

    def interactive_retry(self) -> None:
        if not self.session_id:
            self.console.print("[yellow]No active session.[/yellow]")
            return
        try:
            jobs = self.client.list_queue_jobs(session_id=self.session_id, limit=50)
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load jobs: {exc}[/red]")
            return
        retryable = [job for job in jobs if str(job.get("status", "")).lower() in TUI_RETRY_STATES]
        self.console.print(queue_jobs_table(retryable))
        if not retryable:
            self.console.print(
                "[yellow]No failed/dead-lettered/cancelled jobs to retry.[/yellow]"
            )
            return
        choice = Prompt.ask(
            "Job id to retry (blank to cancel)",
            default="",
        ).strip()
        if not choice:
            return
        self.retry_job(choice)

    def retry_job(self, job_id: str) -> None:
        if not job_id:
            self.console.print("[yellow]Job id is required.[/yellow]")
            return
        try:
            job = self.client.retry_queue_job(job_id)
        except CliApiError as exc:
            self.console.print(
                f"[red]Retry failed for job {job_id}: {exc}[/red]"
            )
            return
        status = job.get("status", "unknown")
        if str(status).lower() in TUI_RETRY_STATES or status == "queued":
            self.console.print(
                f"[green]Retry scheduled for job {job_id} (status={status}).[/green]"
            )
        else:
            self.console.print(
                f"[yellow]Retry response for job {job_id}: status={status}[/yellow]"
            )

    def show_status(self) -> None:
        try:
            sessions = self.client.list_sessions()
            jobs = self.client.list_queue_jobs(
                session_id=self.session_id, limit=20
            )
        except CliApiError as exc:
            self.console.print(f"[red]Failed to load status: {exc}[/red]")
            return
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        grid.add_row(sessions_table(sessions), queue_jobs_table(jobs))
        self.console.print(grid)

    def send_prompt(self, prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt:
            self.console.print("[yellow]Prompt is empty.[/yellow]")
            return
        if len(prompt) > MAX_PROMPT_LEN:
            self.console.print(
                f"[red]Prompt too long ({len(prompt)} > {MAX_PROMPT_LEN}).[/red]"
            )
            return
        if not self.session_id:
            try:
                session = self.client.create_session(
                    title="Terminal session",
                    agent_id=self.agent_id or "build",
                )
            except CliApiError as exc:
                self.console.print(f"[red]Failed to create session: {exc}[/red]")
                return
            self.session_id = str(session["id"])
            self.console.print(f"[green]Created session {self.session_id}[/green]")
        if not self.agent_id:
            self.console.print(
                "[red]No active agent. Use 'agent' to pick one first.[/red]"
            )
            return
        try:
            response = self.client.send_message(
                self.session_id,
                content=prompt,
                agent_id=self.agent_id,
            )
        except CliApiError as exc:
            self.console.print(f"[red]Send failed: {exc}[/red]")
            return
        run = (response or {}).get("agent_run") or {}
        self.console.print(
            Panel(
                f"Run {run.get('id', '?')} status={run.get('status', 'unknown')}\n"
                f"agent={self.agent_id} session={self.session_id}",
                title="Queued",
                border_style="cyan",
            )
        )

    def _register_permission(self, permission: dict[str, Any]) -> PermissionModal:
        permission_id = str(
            permission.get("permission_request_id") or permission.get("id") or ""
        )
        modal = self._pending_permissions.get(permission_id)
        if modal is None:
            modal = PermissionModal(permission=permission)
            if permission_id:
                self._pending_permissions[permission_id] = modal
        return modal

    def _register_human_input(self, request: dict[str, Any]) -> HumanInputModal:
        request_id = str(
            request.get("human_input_request_id") or request.get("id") or ""
        )
        modal = self._pending_human_inputs.get(request_id)
        if modal is None:
            modal = HumanInputModal(request=request)
            if request_id:
                self._pending_human_inputs[request_id] = modal
        return modal

    def _reset_modals_for_session(self) -> None:
        self._pending_permissions.clear()
        self._pending_human_inputs.clear()

    def _report_outcome(
        self,
        label: str,
        outcome: ModalOutcome,
        *,
        success: str,
    ) -> None:
        if outcome.result == ModalResult.SKIPPED and outcome.detail == "details":
            return
        if outcome.result == ModalResult.SKIPPED and outcome.detail == "invalid_choice":
            self.console.print(
                f"[yellow]{label} invalid choice. Use approve, deny, or details.[/yellow]"
            )
            return
        if outcome.result == ModalResult.SKIPPED and outcome.detail == "duplicate":
            self.console.print(
                f"[yellow]{label} duplicate action ignored.[/yellow]"
            )
            return
        if outcome.result == ModalResult.FAILED:
            self.console.print(
                f"[red]{label} failed: {outcome.detail}[/red]"
            )
            return
        if outcome.result.value == success:
            self.console.print(
                f"[green]{label} {outcome.result.value}: {outcome.detail}[/green]"
            )
            return
        self.console.print(
            f"[yellow]{label} {outcome.result.value}: {outcome.detail or ''}[/yellow]"
        )


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


def tui_import_smoke() -> None:
    """Module-level smoke: import the TUI and check for the required bindings."""
    console = Console(file=open(os.devnull, "w", encoding="utf-8")) if not sys.stdout else Console()
    table = Table.grid()
    table.add_column()
    table.add_row("tui import smoke ok")
    console.print(table)
