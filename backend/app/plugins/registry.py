from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.plugins.service import plugin_service
from backend.app.plugins.tools import PluginManifestTool
from backend.app.tools.registry import tool_registry


async def sync_plugin_tools(db: AsyncSession) -> None:
    tool_registry.clear_external("plugin.")
    for row in await plugin_service.list_tools(db, enabled=True):
        tool_registry.register(
            PluginManifestTool(
                name=row.full_name,
                description=row.description,
                input_schema=row.input_schema,
                risk_level=row.risk_level,
                enabled=row.enabled,
            )
        )
