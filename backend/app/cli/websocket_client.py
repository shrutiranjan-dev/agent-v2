from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import websockets

from backend.app.cli.config import CliConfig

FINAL_EVENT_TYPES = {
    "agent_run.completed",
    "agent_run.failed",
    "agent_run.blocked",
}


class SessionEventStream:
    def __init__(self, config: CliConfig, session_id: str) -> None:
        self.config = config
        self.session_id = session_id

    async def events(self, *, stop_on_terminal: bool = False) -> AsyncIterator[dict[str, Any]]:
        path = f"{self.config.ws_url}/ws/sessions/{self.session_id}"
        attempt = 0
        while True:
            try:
                async with websockets.connect(path, open_timeout=self.config.timeout_seconds) as websocket:
                    attempt = 0
                    async for raw in websocket:
                        event = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8"))
                        yield event
                        if stop_on_terminal and event_type(event) in FINAL_EVENT_TYPES:
                            return
            except (OSError, websockets.WebSocketException, TimeoutError):
                attempt += 1
                if attempt > self.config.stream_reconnect_attempts:
                    raise
                await asyncio.sleep(min(2**attempt, 10))


def event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event_type") or "")
