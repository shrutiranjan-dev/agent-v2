"""Live WebSocket event bridge for the TUI.

The Textual app owns a ``TuiEventBridge`` instance per active session. The
bridge runs a background asyncio task that streams events from
``/ws/sessions/{session_id}`` and applies them to a ``TuiState`` reducer.

The bridge is intentionally minimal so it can be unit tested with a fake
``SessionEventStream``: tests construct a state and bridge, push a list of
events, and assert the resulting state.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from backend.app.cli.api_client import CliApiError
from backend.app.cli.tui_state import (
    ConnectionStatus,
    TuiState,
    mark_connection,
    record_error,
)
from backend.app.cli.websocket_client import SessionEventStream

logger = logging.getLogger(__name__)

StateMutator = Callable[[TuiState], None]
Notifier = Callable[[], None]


class StateView(Protocol):
    """Protocol satisfied by ``TuiState`` and any other state holder."""

    def update(self, mutator: StateMutator) -> Any: ...
    def snapshot(self) -> dict[str, Any]: ...


class TuiEventBridge:
    """Bridges a backend WebSocket stream into the ``TuiState`` reducer."""

    def __init__(
        self,
        *,
        state: TuiState,
        stream_factory: Callable[[str], SessionEventStream] | None = None,
        on_state_change: Notifier | None = None,
        replay_buffer: int = 50,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._state = state
        self._stream_factory = stream_factory or self._default_stream_factory
        self._on_state_change = on_state_change or (lambda: None)
        self._replay_buffer = replay_buffer
        self._sleep = sleep
        self._session_id: str | None = None
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_event_keys: list[str] = []

    @staticmethod
    def _default_stream_factory(session_id: str) -> SessionEventStream:
        from backend.app.cli.config import load_cli_config

        return SessionEventStream(load_cli_config(), session_id)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def attach_session(
        self,
        session_id: str | None,
        *,
        state: TuiState | None = None,
    ) -> None:
        """Switch the bridge to a new session id; restarts the loop if needed."""
        target = state or self._state
        self._state = target
        if session_id == self._session_id and self.is_running:
            return
        self._session_id = session_id
        self._stop()
        target.update(
            lambda s: (
                mark_connection(
                    s,
                    ConnectionStatus.CONNECTING if session_id else ConnectionStatus.DISCONNECTED,
                    detail="" if session_id else "no active session",
                ),
            )
        )
        self._on_state_change()
        if session_id is not None:
            self._task = asyncio.create_task(self._run(), name="tui-event-bridge")

    def stop(self) -> None:
        self._stop()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._stop_event = asyncio.Event()

    async def _run(self) -> None:
        session_id = self._session_id
        assert session_id is not None
        attempt = 0
        while not self._stop_event.is_set():
            self._state.update(
                lambda s: mark_connection(s, ConnectionStatus.CONNECTING)
            )
            self._on_state_change()
            try:
                stream = self._stream_factory(session_id)
                async for event in stream.events():
                    if self._stop_event.is_set():
                        break
                    attempt = 0
                    self._handle_event(event)
            except asyncio.CancelledError:
                break
            except CliApiError as exc:
                err = str(exc)
                self._state.update(
                    lambda s, _err=err: (
                        mark_connection(
                            s,
                            ConnectionStatus.FAILED,
                            detail=_err,
                        ),
                        record_error(s, f"event stream error: {_err}"),
                    )
                )
                self._on_state_change()
                break
            except Exception as exc:  # pragma: no cover - network errors
                logger.warning("event stream disconnected: %s", exc)
                err = str(exc)
                attempt += 1
                self._state.update(
                    lambda s, _err=err: mark_connection(
                        s,
                        ConnectionStatus.FAILED,
                        detail=_err,
                    )
                )
                self._on_state_change()
                if attempt > 5:
                    self._state.update(
                        lambda s, _err=err, _attempt=attempt: mark_connection(
                            s,
                            ConnectionStatus.FAILED,
                            detail=f"giving up after {_attempt} attempts: {_err}",
                        )
                    )
                    self._on_state_change()
                    break
                try:
                    await self._sleep(min(2**attempt, 10))
                except asyncio.CancelledError:
                    break
                continue
            self._state.update(
                lambda s: mark_connection(
                    s,
                    ConnectionStatus.DISCONNECTED,
                    detail="event stream closed",
                )
            )
            self._on_state_change()
            break
        if not self._stop_event.is_set():
            self._state.update(
                lambda s: mark_connection(
                    s,
                    ConnectionStatus.DISCONNECTED,
                    detail="event stream ended",
                )
            )
            self._on_state_change()

    def _handle_event(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        from backend.app.cli.tui_state import apply_event

        self._state.update(lambda s: apply_event(s, event))
        self._on_state_change()

    def feed_for_tests(self, events: list[dict[str, Any]]) -> None:
        """Synchronous helper: feed a fixed list of events to the reducer."""
        from backend.app.cli.tui_state import apply_event

        for event in events:
            ev = event
            self._state.update(lambda s, _ev=ev: apply_event(s, _ev))
        self._on_state_change()
