from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.prompt import Prompt

from backend.app.cli.api_client import AgentApiClient
from backend.app.cli.render import event_renderable
from backend.app.cli.websocket_client import SessionEventStream, event_type

PromptFunc = Callable[[str], str]


def handle_permission_request(
    client: AgentApiClient,
    permission: dict[str, Any],
    *,
    prompt: PromptFunc,
    console: Console,
) -> str:
    permission_id = str(permission.get("permission_request_id") or permission.get("id") or "")
    if not permission_id:
        console.print("[red]Permission request did not include an id.[/red]")
        return "missing"
    while True:
        choice = prompt("Approve permission? [approve/deny/details]").strip().lower()
        if choice in {"a", "approve", "y", "yes"}:
            client.approve_permission(permission_id)
            console.print(f"[green]Approved permission {permission_id}[/green]")
            return "approved"
        if choice in {"d", "deny", "n", "no"}:
            client.deny_permission(permission_id)
            console.print(f"[yellow]Denied permission {permission_id}[/yellow]")
            return "denied"
        if choice == "details":
            console.print_json(data=permission)
            continue
        console.print("[yellow]Choose approve, deny, or details.[/yellow]")


def handle_human_input_request(
    client: AgentApiClient,
    request: dict[str, Any],
    *,
    prompt: PromptFunc,
    console: Console,
) -> str:
    request_id = str(request.get("human_input_request_id") or request.get("id") or "")
    if not request_id:
        console.print("[red]Human input request did not include an id.[/red]")
        return "missing"
    choices = [str(choice) for choice in request.get("choices") or []]
    allow_free_text = bool(request.get("allow_free_text"))
    while True:
        answer = prompt("Answer question or type /cancel").strip()
        if answer == "/cancel":
            client.cancel_human_input(request_id, message="cancelled from CLI")
            console.print(f"[yellow]Cancelled human input {request_id}[/yellow]")
            return "cancelled"
        if choices and answer not in choices and not allow_free_text:
            console.print(f"[yellow]Choose one of: {', '.join(choices)}[/yellow]")
            continue
        if not answer:
            console.print("[yellow]Answer cannot be empty.[/yellow]")
            continue
        client.answer_human_input(request_id, answer=answer)
        console.print(f"[green]Answered human input {request_id}[/green]")
        return "answered"


async def stream_chat(
    *,
    client: AgentApiClient,
    stream: SessionEventStream,
    console: Console,
    interactive: bool = True,
) -> None:
    async for event in stream.events(stop_on_terminal=True):
        console.print(event_renderable(event))
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if not interactive:
            continue
        if event_type(event) == "permission.requested":
            handle_permission_request(client, payload, prompt=Prompt.ask, console=console)
        if event_type(event) == "question.requested":
            handle_human_input_request(client, payload, prompt=Prompt.ask, console=console)


def run_chat_stream(
    *,
    client: AgentApiClient,
    stream: SessionEventStream,
    console: Console,
    interactive: bool = True,
) -> None:
    asyncio.run(stream_chat(client=client, stream=stream, console=console, interactive=interactive))
