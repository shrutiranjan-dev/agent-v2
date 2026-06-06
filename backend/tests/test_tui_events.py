"""Tests for the TUI event bridge.

The bridge connects a WebSocket stream to a state reducer. It supports a
``feed_for_tests`` injection path so the reducer logic can be exercised
without a live socket.
"""

# ruff: noqa: E402

from backend.app.cli.tui_events import TuiEventBridge
from backend.app.cli.tui_state import (
    ConnectionStatus,
    TuiState,
    set_agents,
)


def test_bridge_feed_events_dispatches_to_reducer() -> None:
    state = TuiState()
    bridge = TuiEventBridge(state=state)
    assert bridge.is_running is False
    assert bridge.session_id is None
    bridge.feed_for_tests(
        [
            {
                "type": "message.created",
                "payload": {
                    "message": {"role": "assistant", "content": "hello"},
                },
            }
        ]
    )
    assert len(state.messages) == 1
    assert state.messages[0].content == "hello"


def test_bridge_feed_events_records_run_status() -> None:
    state = TuiState()
    bridge = TuiEventBridge(state=state)
    bridge.feed_for_tests(
        [
            {"type": "agent_run.queued", "payload": {}},
            {"type": "agent_run.started", "payload": {}},
        ]
    )
    assert state.run_status.value == "running"


def test_bridge_feed_events_with_unknown_event_is_safe() -> None:
    state = TuiState()
    bridge = TuiEventBridge(state=state)
    bridge.feed_for_tests([{"type": "some.unknown.event", "payload": {}}])
    assert len(state.events) == 1


def test_bridge_notifier_fires_after_each_event() -> None:
    state = TuiState()
    notify_calls: list[int] = []
    bridge = TuiEventBridge(state=state, on_state_change=lambda: notify_calls.append(1))
    bridge.feed_for_tests(
        [
            {"type": "agent_run.queued", "payload": {}},
            {"type": "agent_run.started", "payload": {}},
        ]
    )
    # feed_for_tests fires the notifier once at the end of the batch.
    assert len(notify_calls) == 1


def test_bridge_stop_is_idempotent_when_no_task() -> None:
    state = TuiState()
    bridge = TuiEventBridge(state=state)
    bridge.stop()
    bridge.stop()
    assert bridge.is_running is False


def test_bridge_attach_session_uses_injected_stream_factory() -> None:
    """``attach_session`` should request a stream from the factory and
    transition state to CONNECTING."""
    import asyncio

    state = TuiState()
    set_agents(state, [{"id": "build", "name": "Build", "model_name": "m1"}])

    factory_calls: list[str] = []
    started = asyncio.Event()

    class _FakeStream:
        def __init__(self, session_id: str) -> None:
            factory_calls.append(session_id)
            self.session_id = session_id

        async def events(self, *, stop_on_terminal: bool = False):
            started.set()
            # Block until cancelled by bridge.stop().
            await asyncio.sleep(3600)
            if False:
                yield {}

        def stop(self) -> None:
            return None

    async def _exercise() -> None:
        bridge = TuiEventBridge(state=state, stream_factory=lambda sid: _FakeStream(sid))
        bridge.attach_session("session-42")
        try:
            await asyncio.wait_for(started.wait(), timeout=2.0)
        except TimeoutError:
            pass
        assert factory_calls == ["session-42"]
        assert bridge.session_id == "session-42"
        assert state.connection_status == ConnectionStatus.CONNECTING
        bridge.stop()
        await asyncio.sleep(0)

    asyncio.run(_exercise())


def test_bridge_attach_none_session_marks_disconnected() -> None:
    state = TuiState()
    bridge = TuiEventBridge(state=state)
    bridge.attach_session(None)
    assert state.connection_status == ConnectionStatus.DISCONNECTED
    assert state.connection_detail == "no active session"
