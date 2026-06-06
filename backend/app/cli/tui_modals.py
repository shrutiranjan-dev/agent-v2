"""TUI modal handlers with state-locked double-action prevention.

These are explicit, testable handlers used by the Rich TUI loop and the
``agentv2`` CLI commands. The Rich TUI is not a full Textual application,
so the "modal" name reflects the explicit state machine: a modal is open
exactly once, the action button/choice is consumed exactly once, and the
result is reported to the caller for outer rendering.
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

from backend.app.cli.api_client import AgentApiClient, CliApiError
from backend.app.cli.diff_preview import (
    diff_preview_panel,
    extract_diff_preview,
    should_show_diff,
)

PROMPT_FUNC = type(Prompt.ask)


class ModalState(enum.StrEnum):
    OPEN = "open"
    SUBMITTING = "submitting"
    CLOSED = "closed"


class ModalResult(enum.StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    ANSWERED = "answered"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"


@dataclass
class ModalOutcome:
    result: ModalResult
    detail: str | None = None
    payload: dict[str, Any] | None = None


class _BaseModal:
    """Single-shot state machine guarding a permission/human-input interaction."""

    def __init__(self) -> None:
        self._state: ModalState = ModalState.OPEN
        self._outcome: ModalOutcome | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> ModalState:
        return self._state

    @property
    def outcome(self) -> ModalOutcome | None:
        return self._outcome

    def _begin(self) -> bool:
        with self._lock:
            if self._state != ModalState.OPEN:
                return False
            self._state = ModalState.SUBMITTING
            return True

    def _close(self, outcome: ModalOutcome) -> None:
        with self._lock:
            self._outcome = outcome
            self._state = ModalState.CLOSED

    def _reset(self) -> None:
        with self._lock:
            self._state = ModalState.OPEN
            self._outcome = None


class PermissionModal(_BaseModal):
    """Approve/deny a permission request with single-shot locking."""

    def __init__(self, *, permission: dict[str, Any]) -> None:
        super().__init__()
        self.permission = permission
        self.permission_id = str(
            permission.get("permission_request_id")
            or permission.get("id")
            or ""
        )

    def render(self) -> Panel:
        body = Text()
        body.append(
            f"Permission: {self.permission.get('permission_key', 'unknown')}\n",
            style="bold yellow",
        )
        body.append(f"Resource: {self.permission.get('resource', 'unknown')}\n")
        metadata = (
            self.permission.get("metadata")
            if isinstance(self.permission.get("metadata"), dict)
            else {}
        )
        if metadata.get("risk_level"):
            body.append(f"Risk: {metadata['risk_level']}\n", style="yellow")
        if metadata.get("reason"):
            body.append(f"Reason: {metadata['reason']}\n")
        body.append("Choose approve, deny, or details.")
        if should_show_diff(self.permission):
            return Panel(
                Panel(body, title="Permission Requested", border_style="yellow"),
                title=self.permission_id or "permission",
                border_style="yellow",
            )
        return Panel(body, title="Permission Requested", border_style="yellow")

    def resolve(
        self,
        *,
        client: AgentApiClient,
        choice: str,
        console: Console,
    ) -> ModalOutcome:
        normalized = choice.strip().lower()
        if normalized in {"details", "info"}:
            console.print_json(data=self.permission)
            self._state = ModalState.OPEN
            return ModalOutcome(result=ModalResult.SKIPPED, detail="details")
        if normalized in {"a", "approve", "y", "yes"}:
            action = "approve"
        elif normalized in {"d", "deny", "n", "no"}:
            action = "deny"
        else:
            self._state = ModalState.OPEN
            return ModalOutcome(result=ModalResult.SKIPPED, detail="invalid_choice")
        if not self._begin():
            console.print(
                f"[yellow]Permission {self.permission_id} already resolved; ignoring duplicate {action}.[/yellow]"
            )
            return ModalOutcome(
                result=ModalResult.SKIPPED, detail="duplicate"
            )
        if not self.permission_id:
            self._close(
                ModalOutcome(
                    result=ModalResult.FAILED, detail="missing_permission_id"
                )
            )
            return self._outcome  # type: ignore[return-value]
        try:
            if action == "approve":
                client.approve_permission(self.permission_id)
            else:
                client.deny_permission(self.permission_id)
        except CliApiError as exc:
            self._close(ModalOutcome(result=ModalResult.FAILED, detail=str(exc)))
            return self._outcome  # type: ignore[return-value]
        self._close(
            ModalOutcome(
                result=(
                    ModalResult.APPROVED if action == "approve" else ModalResult.DENIED
                ),
                detail=self.permission_id,
            )
        )
        return self._outcome  # type: ignore[return-value]


class HumanInputModal(_BaseModal):
    """Answer/cancel a human-input request with single-shot locking."""

    def __init__(self, *, request: dict[str, Any]) -> None:
        super().__init__()
        self.request = request
        self.request_id = str(
            request.get("human_input_request_id") or request.get("id") or ""
        )
        self.choices: list[str] = [str(c) for c in (request.get("choices") or [])]
        self.allow_free_text = bool(request.get("allow_free_text"))

    def render(self) -> Panel:
        body = Text()
        body.append(
            str(self.request.get("question", "Question requested")),
            style="bold cyan",
        )
        if self.choices:
            body.append("\nChoices: " + ", ".join(self.choices))
        if self.allow_free_text:
            body.append("\nFree text is allowed.")
        if self.state == ModalState.SUBMITTING:
            body.append("\nSubmitting...", style="yellow")
        elif self.state == ModalState.CLOSED and self._outcome is not None:
            body.append(f"\nResult: {self._outcome.result.value}", style="dim")
        return Panel(body, title="Human Input Requested", border_style="cyan")

    def _validate(self, answer: str) -> str | None:
        if not answer.strip():
            return "Answer cannot be empty."
        if self.choices and answer not in self.choices and not self.allow_free_text:
            return f"Choose one of: {', '.join(self.choices)}"
        return None

    def resolve(
        self,
        *,
        client: AgentApiClient,
        answer: str,
        console: Console,
    ) -> ModalOutcome:
        if answer.strip() == "/cancel":
            if not self._begin():
                console.print(
                    f"[yellow]Human input {self.request_id} already resolved; ignoring duplicate cancel.[/yellow]"
                )
                return ModalOutcome(
                    result=ModalResult.SKIPPED, detail="duplicate"
                )
            try:
                client.cancel_human_input(self.request_id, message="cancelled from CLI")
            except CliApiError as exc:
                self._close(ModalOutcome(result=ModalResult.FAILED, detail=str(exc)))
                return self._outcome  # type: ignore[return-value]
            self._close(
                ModalOutcome(
                    result=ModalResult.CANCELLED, detail=self.request_id
                )
            )
            return self._outcome  # type: ignore[return-value]
        validation_error = self._validate(answer)
        if validation_error is not None:
            self._state = ModalState.OPEN
            return ModalOutcome(
                result=ModalResult.SKIPPED, detail=validation_error
            )
        if not self._begin():
            console.print(
                f"[yellow]Human input {self.request_id} already resolved; ignoring duplicate answer.[/yellow]"
            )
            return ModalOutcome(
                result=ModalResult.SKIPPED, detail="duplicate"
            )
        try:
            client.answer_human_input(self.request_id, answer=answer)
        except CliApiError as exc:
            self._close(ModalOutcome(result=ModalResult.FAILED, detail=str(exc)))
            return self._outcome  # type: ignore[return-value]
        self._close(
            ModalOutcome(result=ModalResult.ANSWERED, detail=self.request_id)
        )
        return self._outcome  # type: ignore[return-value]


class DiffModal:
    """Render the latest diff for a session using the existing preview pipeline."""

    def __init__(
        self,
        *,
        events: list[dict[str, Any]],
        max_lines: int = 200,
    ) -> None:
        self.events = events
        self.max_lines = max_lines
        self._latest = self._find_latest_diff(events)

    @staticmethod
    def _find_latest_diff(events: list[dict[str, Any]]) -> dict[str, Any] | None:
        for event in reversed(events):
            event_type = str(
                event.get("type")
                or event.get("event_type")
                or ""
            )
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "permission.requested" and should_show_diff(payload):
                return {
                    "source": "permission",
                    "title": str(
                        payload.get("permission_key") or "permission"
                    ),
                    "payload": payload,
                }
            if event_type.startswith("tool_call.") and should_show_diff(payload):
                return {
                    "source": event_type,
                    "title": str(
                        payload.get("tool_name") or payload.get("tool") or event_type
                    ),
                    "payload": payload,
                }
        return None

    @property
    def has_diff(self) -> bool:
        preview = extract_diff_preview(self._latest["payload"]) if self._latest else {}
        return bool(preview.get("diff"))

    def render(self) -> Panel:
        if not self._latest:
            return Panel(
                Text("No diff available for this session yet.", style="yellow"),
                title="Diff",
                border_style="yellow",
            )
        preview = extract_diff_preview(self._latest["payload"])
        diff_text = preview.get("diff") or ""
        if diff_text:
            truncated = self._truncate(diff_text)
            header = Text(
                f"{self._latest['title']} ({self._latest['source']})\n", style="bold"
            )
            header.append(
                f"Targets: {', '.join(preview.get('target_paths') or []) or 'unknown'}\n"
            )
            header.append(f"Risk: {preview.get('risk_level', 'unknown')}")
            return Panel(
                Panel(
                    Syntax(truncated, "diff", word_wrap=True),
                    title="Diff",
                    border_style="yellow",
                ),
                title=header,
                border_style="yellow",
            )
        return diff_preview_panel(self._latest["payload"])

    def _truncate(self, diff_text: str) -> str:
        lines = diff_text.splitlines()
        if len(lines) <= self.max_lines:
            return diff_text
        kept = lines[: self.max_lines]
        kept.append(f"... ({len(lines) - self.max_lines} more lines truncated)")
        return "\n".join(kept)
