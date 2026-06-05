from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.postgres import get_session
from backend.app.mcp.registry import sync_mcp_tools
from backend.app.plugins.registry import sync_plugin_tools
from backend.app.tools.registry import tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(db: AsyncSession = Depends(get_session)) -> dict:
    await sync_mcp_tools(db)
    await sync_plugin_tools(db)
    return {"tools": tool_registry.list()}
