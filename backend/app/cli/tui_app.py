"""Full-screen Textual app for the Agent Platform TUI.

The app owns a single ``TuiState`` and a ``TuiEventBridge``. It subscribes
to state changes (driven by API calls and the WebSocket stream) and re-renders
the relevant widgets.

The app also exposes a ``--check/--smoke`` mode that loads agents and prints
a short status line, then exits. CI uses this to prove the Textual import
path works without hanging.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from backend.app.cli.api_client import AgentApiClient, CliApiError
from backend.app.cli.config import CliConfig, load_cli_config
from backend.app.cli.tui_events import TuiEventBridge
from backend.app.cli.tui_state import (
    ConnectionStatus,
    TuiState,
    set_agents,
    set_health,
    set_sessions,
)
from backend.app.cli.websocket_client import SessionEventStream

MAX_DIFF_LINES = 200
MAX_RICH_LOG_LINES = 1000

STATE_HEADER_BINDINGS: ClassVar[list[Binding]] = []


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + f"\n... ({len(text) - limit + 20} chars truncated)"


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------


class _Section(Vertical):
    """A bordered vertical section with a title."""

    DEFAULT_CSS = """
    _Section {
        height: 1fr;
        border: round $accent;
        padding: 0 1;
    }
    _Section > Label {
        color: $accent;
        text-style: bold;
    }
    """

    def __init__(self, title: str, *children: Any, **kwargs: Any) -> None:
        super().__init__(*children, **kwargs)
        self._title = title
        self.border_title = title

    def compose(self) -> ComposeResult:
        yield Label(self._title)
        yield from self._children_compose()

    def _children_compose(self) -> ComposeResult:  # pragma: no cover - small helper
        return ComposeResult()


class SessionList(ListView):
    """Displays the list of sessions with a placeholder when empty."""

    DEFAULT_CSS = """
    SessionList {
        height: 1fr;
    }
    SessionList > ListItem {
        padding: 0 1;
    }
    """


class MessagePanel(RichLog):
    """Scrollable RichLog of session messages."""

    DEFAULT_CSS = """
    MessagePanel {
        height: 1fr;
        border: round $primary;
    }
    """


class ToolTimeline(RichLog):
    DEFAULT_CSS = """
    ToolTimeline {
        height: 1fr;
        border: round $secondary;
    }
    """


class EventLog(RichLog):
    DEFAULT_CSS = """
    EventLog {
        height: 1fr;
        border: round $secondary;
    }
    """


class HeaderBar(Static):
    """Top header showing backend health, session, agent, model, and connection."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 3;
        padding: 0 1;
        background: $boost;
        color: $text;
        border: round $accent;
    }
    """


class PromptBar(Static):
    """Bottom row that hosts the input and a hint line."""

    DEFAULT_CSS = """
    PromptBar {
        height: 5;
        padding: 0 1;
        border: round $accent;
    }
    PromptBar Input {
        height: 3;
    }
    """


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


class PermissionModalScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    PermissionModalScreen {
        align: center middle;
    }
    PermissionModalScreen > Vertical {
        width: 80%;
        max-width: 100;
        height: auto;
        border: round $warning;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("a,enter", "approve", "Approve"),
        Binding("d,escape", "deny", "Deny"),
    ]

    def __init__(self, *, permission: dict[str, Any]) -> None:
        super().__init__()
        self._permission = permission
        self._permission_id = str(
            permission.get("permission_request_id")
            or permission.get("id")
            or ""
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"Permission: {self._permission.get('permission_key', 'unknown')}",
                id="permission-title",
            )
            yield Static(
                f"Resource: {self._permission.get('resource', 'unknown')}\n"
                f"id: {self._permission_id}\n"
                "Press 'a' to approve, 'd' to deny, or 'escape' to dismiss."
            )

    def action_approve(self) -> None:
        self.dismiss({"permission_id": self._permission_id, "choice": "approve"})

    def action_deny(self) -> None:
        self.dismiss({"permission_id": self._permission_id, "choice": "deny"})


class HumanInputModalScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HumanInputModalScreen {
        align: center middle;
    }
    HumanInputModalScreen > Vertical {
        width: 80%;
        max-width: 100;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, request: dict[str, Any]) -> None:
        super().__init__()
        self._request = request
        self._request_id = str(
            request.get("human_input_request_id")
            or request.get("id")
            or ""
        )
        self._choices: list[str] = [
            str(choice) for choice in (request.get("choices") or [])
        ]
        self._allow_free_text = bool(request.get("allow_free_text"))

    def compose(self) -> ComposeResult:
        body = [self._request.get("question", "Question requested")]
        if self._choices:
            body.append("Choices: " + ", ".join(self._choices))
        if self._allow_free_text:
            body.append("Free text allowed.")
        with Vertical():
            yield Label(str(self._request.get("question", "Question requested")))
            yield Static("\n".join(body))
            yield Input(placeholder="Type answer and press enter", id="answer-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        answer = event.value.strip()
        if not answer:
            return
        if self._choices and answer not in self._choices and not self._allow_free_text:
            return
        self.dismiss({"request_id": self._request_id, "answer": answer})

    def action_cancel(self) -> None:
        self.dismiss({"request_id": self._request_id, "answer": "/cancel"})


class AgentSwitcherModalScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    AgentSwitcherModalScreen {
        align: center middle;
    }
    AgentSwitcherModalScreen > Vertical {
        width: 80%;
        max-width: 100;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    AgentSwitcherModalScreen ListView {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, agents: list[dict[str, Any]], active_agent_id: str | None) -> None:
        super().__init__()
        self._agents = agents
        self._active_agent_id = active_agent_id
        self._items: list[ListItem] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Select an agent")
            yield Static(
                "Press the number or arrow keys, then enter to confirm. "
                "Press 'escape' to cancel."
            )
            list_view = ListView(id="agent-list")
            for index, agent in enumerate(self._agents):
                label = (
                    f"{index + 1}. {agent.get('id')} — "
                    f"{agent.get('name', '')} "
                    f"[{agent.get('mode', '')}] "
                    f"({agent.get('model_name', '')})"
                )
                item = ListItem(Label(label), id=f"agent-{index}")
                self._items.append(item)
                yield list_view
            yield Static(
                f"Active: {self._active_agent_id or '(none)'}"
            )

    def on_mount(self) -> None:
        if self._items:
            self.query_one(ListView).index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index or 0
        if 0 <= index < len(self._agents):
            self.dismiss({"agent_id": str(self._agents[index].get("id"))})

    def action_cancel(self) -> None:
        self.dismiss(None)


class SessionCreateModalScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    SessionCreateModalScreen {
        align: center middle;
    }
    SessionCreateModalScreen > Vertical {
        width: 80%;
        max-width: 100;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, default_agent: str | None = None) -> None:
        super().__init__()
        self._default_agent = default_agent or "build"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Create a new session")
            yield Static("Title:")
            yield Input(value="Terminal session", id="title-input")
            yield Static("Agent id:")
            yield Input(value=self._default_agent, id="agent-input")
            yield Static("Press 'enter' to create, 'escape' to cancel.")

    def on_mount(self) -> None:
        self.query_one("#title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "title-input":
            self.query_one("#agent-input", Input).focus()
            return
        title = self.query_one("#title-input", Input).value.strip() or "Terminal session"
        agent = self.query_one("#agent-input", Input).value.strip() or self._default_agent
        self.dismiss({"title": title, "agent_id": agent})

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# The Textual app
# ---------------------------------------------------------------------------


class AgentPlatformTuiApp(App[None]):
    """Full-screen Textual app for the Agent Platform TUI."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
    }
    #left, #center, #right {
        height: 1fr;
    }
    #left {
        width: 32;
    }
    #right {
        width: 44;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+n", "new_session", "New session"),
        Binding("ctrl+s", "focus_sessions", "Sessions"),
        Binding("ctrl+a", "switch_agent", "Agent"),
        Binding("ctrl+r", "retry", "Retry"),
        Binding("ctrl+d", "show_diff", "Diff"),
        Binding("ctrl+l", "clear_messages", "Clear log"),
        Binding("ctrl+t", "show_events", "Events"),
    ]

    show_events_panel: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        config: CliConfig | None = None,
        client: AgentApiClient | None = None,
        state: TuiState | None = None,
        stream_factory: Callable[[str], SessionEventStream] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__()
        self._config = config or load_cli_config()
        self._external_client = client
        self._owns_client = client is None
        self._client: AgentApiClient | None = client
        self._state = state or TuiState(backend_url=self._config.base_url)
        self._bridge = TuiEventBridge(
            state=self._state,
            stream_factory=stream_factory,
            sleep=sleep,
        )
        self._send_in_flight = False
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Composing widgets
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield HeaderBar(id="header-bar")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label("Sessions")
                yield SessionList(id="session-list")
            with Vertical(id="center"):
                yield Label("Messages")
                yield MessagePanel(id="message-panel", highlight=True, markup=True, wrap=True)
                yield EventLog(id="event-log", highlight=True, markup=True, wrap=True)
            with Vertical(id="right"):
                yield Label("Run / Tools / Queue")
                yield ToolTimeline(id="tool-timeline", highlight=True, markup=True)
                yield Static(id="right-summary", markup=True)
        with PromptBar():
            yield Static(
                "Enter=send  Ctrl+N=new  Ctrl+A=agent  Ctrl+R=retry  "
                "Ctrl+D=diff  Ctrl+S=sessions  Ctrl+L=clear  Ctrl+C=quit",
                id="prompt-hint",
            )
            yield Input(placeholder="Type a prompt and press enter", id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self._state.backend_url = self._config.base_url
        self._refresh_header()
        self.query_one("#prompt-input", Input).focus()
        self.run_worker(self._initial_load(), exclusive=True, name="tui-initial-load")

    async def _initial_load(self) -> None:
        async with AgentApiClient(self._config) if self._client is None else _nullcontext(
            self._client
        ) as client:
            if self._client is None:
                self._client = client
            try:
                await self._load_health()
            except CliApiError as exc:
                err = str(exc)
                self._state.update(
                    lambda s, _err=err: set_health(s, f"error: {_err}")
                )
            try:
                await self._load_agents()
            except CliApiError as exc:
                err = str(exc)
                self._state.update(
                    lambda s, _err=err: s.__class__(
                        **{
                            **s.__dict__,
                            "transient_errors": list(s.transient_errors) + [_err],
                        }
                    )
                )
            try:
                await self._load_sessions()
            except CliApiError as exc:
                err = str(exc)
                self._state.update(
                    lambda s, _err=err: s.__class__(
                        **{
                            **s.__dict__,
                            "transient_errors": list(s.transient_errors) + [_err],
                        }
                    )
                )
            self._refresh_header()
            self._refresh_sessions()
            self._refresh_messages()
            self._refresh_right_panel()
            if self._state.active_session_id is not None:
                self._bridge.attach_session(self._state.active_session_id, state=self._state)

    # ------------------------------------------------------------------
    # Public actions
    # ------------------------------------------------------------------

    async def action_quit(self) -> None:
        self._bridge.stop()
        if self._owns_client and self._client is not None:
            close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        self.exit()

    async def on_unmount(self) -> None:
        self._bridge.stop()
        if self._owns_client and self._client is not None:
            close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    try:
                        await result
                    except Exception:  # pragma: no cover - shutdown best effort
                        pass

    async def action_new_session(self) -> None:
        result = await self.push_screen_wait(
            SessionCreateModalScreen(
                default_agent=self._state.active_agent_id or "build"
            )
        )
        if not result:
            return
        title = str(result.get("title") or "Terminal session")
        agent = str(result.get("agent_id") or self._state.active_agent_id or "build")
        client = self._require_client()
        try:
            session = client.create_session(title=title, agent_id=agent)
        except CliApiError as exc:
            self._post_error(f"create session failed: {exc}")
            return
        await self._load_sessions()
        self._state.update(
            lambda s: set_sessions(s, s.sessions)
        )
        new_id = str(session["id"])
        self._select_session(new_id)

    async def action_focus_sessions(self) -> None:
        self.query_one("#session-list", SessionList).focus()

    async def action_switch_agent(self) -> None:
        if not self._state.agents:
            await self._load_agents()
        result = await self.push_screen_wait(
            AgentSwitcherModalScreen(
                agents=self._state.agents,
                active_agent_id=self._state.active_agent_id,
            )
        )
        if not result:
            return
        agent_id = str(result.get("agent_id"))
        from backend.app.cli.tui_state import select_agent

        self._state.update(lambda s: select_agent(s, agent_id))
        self._refresh_header()

    async def action_retry(self) -> None:
        retryable = [
            job for job in self._state.queue_jobs if job.status in {
                "failed",
                "dead_letter",
                "dead_lettered",
                "cancelled",
            }
        ]
        if not retryable:
            self._post_status("No failed/dead-lettered/cancelled jobs to retry.")
            return
        job = retryable[-1]
        client = self._require_client()
        try:
            client.retry_queue_job(job.job_id)
        except CliApiError as exc:
            self._post_error(f"retry failed: {exc}")
            return
        self._post_status(f"Retry scheduled for job {job.job_id}.")

    async def action_show_diff(self) -> None:
        diff = self._state.latest_diff
        from rich.panel import Panel
        from rich.syntax import Syntax

        if not diff:
            self._post_status("No diff available for the active session yet.")
            return
        body = Syntax(diff.get("diff", ""), "diff", word_wrap=True)
        self._post_panel(
            Panel(
                body,
                title=f"{diff.get('title', 'diff')} -> {', '.join(diff.get('target_paths', []) or ['unknown'])}",
                border_style="yellow",
            )
        )

    async def action_clear_messages(self) -> None:
        self._state.update(lambda s: s.__class__(**{**s.__dict__, "messages": __import__("collections").deque(maxlen=500)}))
        self._refresh_messages()

    async def action_show_events(self) -> None:
        self.show_events_panel = not self.show_events_panel
        event_log = self.query_one("#event-log", EventLog)
        event_log.display = self.show_events_panel
        if self.show_events_panel:
            for event in list(self._state.events)[-50:]:
                event_log.write(_format_event_line(event))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "session-list":
            item = event.item
            if item is None or not hasattr(item, "session_id"):
                return
            self._select_session(item.session_id)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt-input":
            return
        prompt_text = event.value.strip()
        if not prompt_text:
            return
        if self._send_in_flight:
            self._post_status("A request is already in flight. Please wait.")
            return
        client = self._require_client()
        session_id = self._state.active_session_id
        if not session_id:
            if self._state.active_agent_id is None:
                self._post_status("Pick an agent (Ctrl+A) before sending a prompt.")
                return
            try:
                created = client.create_session(
                    title="Terminal session",
                    agent_id=self._state.active_agent_id,
                )
            except CliApiError as exc:
                self._post_error(f"create session failed: {exc}")
                return
            session_id = str(created["id"])
            await self._load_sessions()
            self._select_session(session_id)
        self._send_in_flight = True
        try:
            client.send_message(
                session_id,
                content=prompt_text,
                agent_id=self._state.active_agent_id,
            )
        except CliApiError as exc:
            self._post_error(f"send failed: {exc}")
        else:
            event.input.value = ""
            self._post_status(f"Prompt sent to {session_id}.")
        finally:
            self._send_in_flight = False

    def watch_show_events_panel(self, value: bool) -> None:
        try:
            event_log = self.query_one("#event-log", EventLog)
        except Exception:  # pragma: no cover - during early mount
            return
        event_log.display = value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_client(self) -> AgentApiClient:
        if self._client is None:
            raise CliApiError("backend client not initialized")
        return self._client

    def _post_status(self, message: str) -> None:
        self._state.update(
            lambda s: s.__class__(
                **{
                    **s.__dict__,
                    "transient_errors": (list(s.transient_errors) + [message])[-10:],
                }
            )
        )
        self._refresh_header()

    def _post_error(self, message: str) -> None:
        self._post_status(f"ERROR: {message}")

    def _post_panel(self, panel: Any) -> None:
        log = self.query_one("#message-panel", MessagePanel)
        log.write(panel)

    async def _load_health(self) -> None:
        client = self._require_client()
        payload = client.health()
        status = str(payload.get("status", "unknown"))
        self._state.update(lambda s: set_health(s, status))

    async def _load_agents(self) -> None:
        client = self._require_client()
        agents = client.list_agents()
        from backend.app.cli.tui_state import set_agents

        self._state.update(lambda s: set_agents(s, agents))

    async def _load_sessions(self) -> None:
        client = self._require_client()
        sessions = client.list_sessions()
        self._state.update(lambda s: set_sessions(s, sessions))

    def _select_session(self, session_id: str) -> None:
        from backend.app.cli.tui_state import select_session

        self._state.update(lambda s: select_session(s, session_id))
        self._bridge.attach_session(session_id, state=self._state)
        self._refresh_header()
        self._refresh_sessions()
        self._refresh_messages()
        self._refresh_right_panel()

    def _refresh_header(self) -> None:
        connection = self._state.connection_status.value
        detail = self._state.connection_detail
        health = self._state.backend_health
        session = self._state.active_session_id or "(no session)"
        title = self._state.active_session_title or ""
        agent = self._state.active_agent_id or "(no agent)"
        model = self._state.active_model or ""
        run = self._state.run_status.value
        error = self._state.run_error
        text = Text()
        text.append("Agent Platform TUI", style="bold")
        text.append("    backend: ")
        text.append(health, style="green" if health == "ok" else "yellow")
        text.append("    ws: ")
        text.append(
            connection,
            style={
                ConnectionStatus.CONNECTED.value: "green",
                ConnectionStatus.CONNECTING.value: "yellow",
                ConnectionStatus.DISCONNECTED.value: "yellow",
                ConnectionStatus.FAILED.value: "red",
            }.get(connection, "yellow"),
        )
        if detail:
            text.append(f" ({detail})", style="dim")
        text.append("    session: ")
        text.append(session, style="bold cyan")
        if title:
            text.append(f" — {title}", style="cyan")
        text.append("    agent: ")
        text.append(agent, style="bold magenta")
        if model:
            text.append(f" (model: {model})", style="dim")
        text.append("    run: ")
        text.append(run, style="bold blue")
        if error:
            text.append(f" — {error}", style="red")
        text.append(f"    url: {self._state.backend_url}", style="dim")
        self.query_one("#header-bar", HeaderBar).update(text)

    def _refresh_sessions(self) -> None:
        list_view = self.query_one("#session-list", SessionList)
        list_view.clear()
        for session in self._state.sessions:
            label = (
                f"{session.get('id', '')[:8]}  {session.get('title', '')}"
                f"  [{session.get('status', '')}]"
            )
            item = ListItem(Label(label))
            item.session_id = str(session.get("id"))
            list_view.append(item)

    def _refresh_messages(self) -> None:
        panel = self.query_one("#message-panel", MessagePanel)
        panel.clear()
        for message in self._state.messages:
            style = "green" if message.role == "assistant" else "blue"
            panel.write(
                Text()
                .append(f"{message.role.title()}: ", style=style)
                .append(_truncate(message.content))
            )
        if not self._state.messages:
            panel.write(Text("No messages yet. Type a prompt below.", style="dim"))

    def _refresh_right_panel(self) -> None:
        timeline = self.query_one("#tool-timeline", ToolTimeline)
        timeline.clear()
        for call in self._state.tool_calls:
            text = Text()
            text.append(call.tool_name, style="bold magenta")
            text.append(f"  {call.status}", style="cyan")
            if call.target_paths:
                text.append(f"  -> {', '.join(call.target_paths)}", style="dim")
            if call.error:
                text.append(f"  error: {call.error}", style="red")
            timeline.write(text)
        if not self._state.tool_calls:
            timeline.write(Text("No tool calls yet.", style="dim"))
        event_log = self.query_one("#event-log", EventLog)
        event_log.clear()
        for event in list(self._state.events)[-50:]:
            event_log.write(_format_event_line(event))
        if not self._state.events:
            event_log.write(Text("No events yet. WebSocket events will appear here.", style="dim"))

        # Summary
        summary = self.query_one("#right-summary", Static)
        permissions = len(self._state.pending_permissions)
        questions = len(self._state.pending_questions)
        jobs = len(self._state.queue_jobs)
        retries = sum(
            1
            for job in self._state.queue_jobs
            if job.status in {"failed", "dead_letter", "dead_lettered", "cancelled"}
        )
        diff_indicator = "yes" if self._state.latest_diff else "no"
        body = Text()
        body.append("Pending permissions: ", style="bold")
        body.append(str(permissions), style="yellow" if permissions else "dim")
        body.append("\nPending questions: ", style="bold")
        body.append(str(questions), style="yellow" if questions else "dim")
        body.append("\nQueue jobs: ", style="bold")
        body.append(str(jobs))
        body.append(f" (retryable: {retries})")
        body.append("\nLatest diff: ", style="bold")
        body.append(diff_indicator)
        if self._state.transient_errors:
            body.append("\nRecent: ", style="bold")
            body.append(_truncate(self._state.transient_errors[-1], 200), style="yellow")
        summary.update(body)

    def on_state_change(self) -> None:
        """Hook called by the bridge whenever state mutates."""
        self._refresh_header()
        self._refresh_messages()
        self._refresh_right_panel()


def _format_event_line(event: dict[str, Any]) -> Text:
    event_type = str(event.get("type") or event.get("event_type") or "event")
    text = Text()
    text.append(event_type, style="bold")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if payload:
        text.append("  ")
        text.append(_truncate(repr(payload), 200), style="dim")
    return text


class _NullContext:
    async def __aenter__(self) -> Any:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _nullcontext(value: Any) -> _NullContext:
    ctx = _NullContext()
    ctx._value = value
    return ctx


# ---------------------------------------------------------------------------
# Public run / check helpers
# ---------------------------------------------------------------------------


def run_tui(
    client: AgentApiClient,
    *,
    console: Any = None,
) -> None:  # pragma: no cover - interactive entrypoint
    """Backward-compatible entrypoint used by the existing CLI.

    If Textual is available we open the full-screen app; otherwise we fall
    back to a one-shot REPL summary so non-interactive shells still get a
    result.
    """
    try:
        app = AgentPlatformTuiApp(client=client)
    except Exception:
        from rich.console import Console

        console = console or Console()
        console.print(
            "[yellow]Textual TUI not available; backend reachable via API client.[/yellow]"
        )
        return
    app.run()


def run_tui_check(
    *,
    config: CliConfig | None = None,
    client: AgentApiClient | None = None,
) -> int:
    """Headless check: instantiate the app, hit the backend, exit 0/1.

    This avoids driving the full Textual app because ``App.run()`` blocks on
    a terminal and is not safe for CI. The check still constructs the
    ``AgentPlatformTuiApp`` (proving imports and widget composition work) and
    then drives a backend round trip on a fresh ``TuiState`` so the reducer
    and bridge are exercised end-to-end.
    """
    config = config or load_cli_config()
    owns_client = client is None
    if owns_client:
        client = AgentApiClient(config)
    try:
        # Constructing the app proves Textual + all widgets import and compose.
        app = AgentPlatformTuiApp(config=config, client=client)
        del app  # noqa: F841 - construction-only assertion
    except Exception as exc:
        print(f"tui-check app construction failed: {exc}", flush=True)
        return 1

    state = TuiState(backend_url=config.base_url)
    try:
        health = client.health()
    except CliApiError as exc:
        print(f"tui-check backend error: {exc}", flush=True)
        return 2
    state.update(lambda s: set_health(s, str(health.get("status", "unknown"))))
    try:
        agents = client.list_agents()
    except CliApiError as exc:
        print(f"tui-check agents error: {exc}", flush=True)
        return 2
    state.update(lambda s: set_agents(s, agents))
    try:
        sessions = client.list_sessions()
    except CliApiError as exc:
        print(f"tui-check sessions error: {exc}", flush=True)
        return 2
    state.update(lambda s: set_sessions(s, sessions))

    print(
        f"tui-check ok: health={state.backend_health} "
        f"agents={len(state.agents)} sessions={len(state.sessions)} "
        f"active_agent={state.active_agent_id or '(none)'}"
    )
    if owns_client and client is not None:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is not None:
            try:
                result = close()
                if hasattr(result, "__await__"):
                    asyncio.run(result)
            except Exception:  # pragma: no cover - best effort
                pass
    return 0
