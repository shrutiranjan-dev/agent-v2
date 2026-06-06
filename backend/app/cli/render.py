from __future__ import annotations

from typing import Any

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.app.cli.diff_preview import diff_preview_panel, should_show_diff

TERMINAL_EVENTS = {
    "agent_run.completed",
    "agent_run.failed",
    "agent_run.blocked",
    "permission.denied",
    "question.cancelled",
}


def render_health(payload: dict[str, Any]) -> RenderableType:
    status = payload.get("status", "unknown")
    style = "green" if status in {"ok", "healthy"} else "yellow"
    return Panel(Text(str(status), style=style), title="Backend Health")


def agents_table(agents: list[dict[str, Any]]) -> Table:
    table = Table(title="Agents")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Mode")
    table.add_column("Max steps", justify="right")
    table.add_column("Description")
    for agent in agents:
        table.add_row(
            str(agent.get("id", "")),
            str(agent.get("name", "")),
            str(agent.get("mode", "")),
            str(agent.get("max_steps", "")),
            str(agent.get("description", "")),
        )
    return table


def sessions_table(sessions: list[dict[str, Any]]) -> Table:
    table = Table(title="Sessions")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Updated")
    for session in sessions:
        table.add_row(
            str(session.get("id", "")),
            str(session.get("title", "")),
            str(session.get("agent_id", "")),
            str(session.get("status", "")),
            str(session.get("updated_at", "")),
        )
    return table


def queue_jobs_table(jobs: list[dict[str, Any]]) -> Table:
    table = Table(title="Queue Jobs")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Session")
    table.add_column("Attempts", justify="right")
    for job in jobs:
        table.add_row(
            str(job.get("id") or job.get("queue_job_id") or ""),
            str(job.get("job_type", "")),
            str(job.get("status", "")),
            str(job.get("session_id") or ""),
            f"{job.get('attempt_count', 0)}/{job.get('max_attempts', '')}",
        )
    return table


def event_renderable(event: dict[str, Any]) -> RenderableType:
    event_type = str(event.get("type") or event.get("event_type") or "event")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if event_type == "message.created":
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        role = str(message.get("role", "message"))
        content = str(message.get("content", ""))
        body: RenderableType = Markdown(content) if role == "assistant" else Text(content)
        return Panel(body, title=f"{role.title()} Message", border_style="green" if role == "assistant" else "blue")
    if event_type.startswith("tool_call."):
        return _tool_event_panel(event_type, payload)
    if event_type == "permission.requested":
        return permission_panel(payload)
    if event_type == "question.requested":
        return human_input_panel(payload)
    if event_type.endswith(".failed") or event_type.endswith(".blocked"):
        return Panel(str(payload.get("error") or payload), title=event_type, border_style="red")
    return Panel(_payload_summary(payload), title=event_type, border_style="dim")


def permission_panel(permission: dict[str, Any]) -> RenderableType:
    body = Text()
    body.append(f"Permission: {permission.get('permission_key', 'unknown')}\n", style="bold yellow")
    body.append(f"Resource: {permission.get('resource', 'unknown')}\n")
    metadata = permission.get("metadata") if isinstance(permission.get("metadata"), dict) else {}
    if metadata.get("risk_level"):
        body.append(f"Risk: {metadata['risk_level']}\n", style="yellow")
    if metadata.get("reason"):
        body.append(f"Reason: {metadata['reason']}\n")
    body.append("Use approve, deny, or details in the terminal prompt.")
    if should_show_diff(permission):
        return Group(Panel(body, title="Permission Requested", border_style="yellow"), diff_preview_panel(permission))
    return Panel(body, title="Permission Requested", border_style="yellow")


def human_input_panel(request: dict[str, Any]) -> Panel:
    body = Text()
    body.append(str(request.get("question", "Question requested")), style="bold cyan")
    choices = request.get("choices")
    if choices:
        body.append("\nChoices: " + ", ".join(str(choice) for choice in choices))
    if request.get("allow_free_text"):
        body.append("\nFree text is allowed.")
    return Panel(body, title="Human Input Requested", border_style="cyan")


def artifacts_table(artifacts: list[dict[str, Any]]) -> Table:
    table = Table(title="Artifacts")
    table.add_column("Name", style="bold")
    table.add_column("Kind")
    table.add_column("Size", justify="right")
    table.add_column("Created")
    for artifact in artifacts:
        table.add_row(
            str(artifact.get("name", "")),
            str(artifact.get("kind", "")),
            str(artifact.get("size_bytes") or ""),
            str(artifact.get("created_at", "")),
        )
    return table


def render_error(error: Exception) -> Panel:
    return Panel(str(error), title=error.__class__.__name__, border_style="red")


def events_table(events: list[dict[str, Any]]) -> Table:
    table = Table(title="Events")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type", style="bold")
    table.add_column("Status")
    table.add_column("Resource")
    table.add_column("Risk")
    table.add_column("Created")
    for event in events:
        event_id = str(
            event.get("id")
            or event.get("permission_request_id")
            or event.get("human_input_request_id")
            or event.get("queue_job_id")
            or event.get("event_id")
            or ""
        )
        event_type = str(
            event.get("type")
            or event.get("event_type")
            or event.get("kind")
            or "event"
        )
        status = str(
            event.get("status")
            or (event.get("payload") or {}).get("status")
            or ""
        )
        resource = str(
            event.get("resource")
            or (event.get("payload") or {}).get("resource")
            or ""
        )
        metadata = (event.get("payload") or {}).get("metadata") or {}
        risk = str(
            event.get("risk_level")
            or metadata.get("risk_level")
            or ""
        )
        created = str(
            event.get("created_at")
            or event.get("timestamp")
            or ""
        )
        table.add_row(event_id, event_type, status, resource, risk, created)
    return table


def diff_renderable(payload: dict[str, Any]) -> RenderableType:
    return diff_preview_panel(payload)


def print_event(console: Console, event: dict[str, Any]) -> None:
    console.print(event_renderable(event))


def _tool_event_panel(event_type: str, payload: dict[str, Any]) -> RenderableType:
    tool = payload.get("tool_name") or payload.get("tool") or "tool"
    status = payload.get("status") or event_type.rsplit(".", 1)[-1]
    body = Text(f"{tool} -> {status}")
    if payload.get("error"):
        body.append(f"\n{payload['error']}", style="red")
    if should_show_diff(payload):
        return Group(Panel(body, title=event_type, border_style="magenta"), diff_preview_panel(payload))
    return Panel(body, title=event_type, border_style="magenta")


def _payload_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "(no payload)"
    preferred = ["id", "status", "error", "permission_request_id", "human_input_request_id", "job_id"]
    lines = [f"{key}: {payload[key]}" for key in preferred if key in payload and payload[key] is not None]
    return "\n".join(lines) if lines else str(payload)
