from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.runtime.event_bus import event_bus

logger = logging.getLogger(__name__)

PluginHook = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None] | dict[str, Any] | None]


@dataclass(slots=True)
class HookRegistration:
    name: str
    callback: PluginHook
    plugin_name: str = "internal"
    blocking: bool = False


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, list[HookRegistration]] = defaultdict(list)

    def clear(self) -> None:
        self._hooks.clear()

    def register(self, name: str, callback: PluginHook, *, plugin_name: str = "internal", blocking: bool = False) -> None:
        self._hooks[name].append(
            HookRegistration(name=name, callback=callback, plugin_name=plugin_name, blocking=blocking)
        )

    async def trigger(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        current = payload
        for hook in list(self._hooks.get(name, [])):
            try:
                result = hook.callback(current)
                if hasattr(result, "__await__"):
                    result = await result  # type: ignore[assignment]
                if isinstance(result, dict):
                    current = result
            except Exception as exc:
                logger.warning("plugin hook failed", extra={"hook": name, "plugin": hook.plugin_name, "error": str(exc)})
                if db is not None:
                    await event_bus.publish(
                        db,
                        event_type=EventType.PLUGIN_HOOK_FAILED,
                        severity="warning",
                        payload={"hook": name, "plugin": hook.plugin_name, "error": str(exc)},
                    )
                if hook.blocking:
                    raise
        return current


hook_registry = HookRegistry()


async def trigger_hook(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await hook_registry.trigger(name, payload)
