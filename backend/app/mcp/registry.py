from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.mcp.service import mcp_service
from backend.app.mcp.tools import McpWrappedTool
from backend.app.tools.registry import tool_registry


async def sync_mcp_tools(db: AsyncSession) -> None:
    tool_registry.clear_external("mcp.")
    for row in await mcp_service.list_tools(db, enabled=True):
        tool_registry.register(
            McpWrappedTool(
                name=row.full_name,
                description=row.description,
                input_schema=row.input_schema,
                risk_level=row.risk_level,
                enabled=row.enabled,
            )
        )
