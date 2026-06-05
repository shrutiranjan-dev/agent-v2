from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.postgres import get_session
from backend.app.plugins.registry import sync_plugin_tools
from backend.app.plugins.service import (
    PluginLoadRequest,
    plugin_service,
    serialize_plugin,
    serialize_plugin_tool,
)
from backend.app.runtime.tenant import ensure_runtime_tenant

router = APIRouter(tags=["plugins"])


class PluginLoadApiRequest(BaseModel):
    manifest_path: str
    trusted: bool = False


@router.get("/plugins")
async def list_plugins(
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    rows = await plugin_service.list_plugins(
        db,
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
    )
    return {"plugins": [serialize_plugin(row) for row in rows]}


@router.post("/plugins/load")
async def load_plugin(
    payload: PluginLoadApiRequest,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    row = await plugin_service.load(
        db,
        PluginLoadRequest(
            manifest_path=payload.manifest_path,
            organization_id=tenant.organization_id,
            project_id=tenant.project_id,
            workspace_id=tenant.workspace_id,
            trusted=payload.trusted,
        ),
    )
    await sync_plugin_tools(db)
    await db.commit()
    return {"plugin": serialize_plugin(row)}


@router.post("/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await plugin_service.set_enabled(db, plugin_id, True)
    await sync_plugin_tools(db)
    await db.commit()
    return {"plugin": serialize_plugin(row)}


@router.post("/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await plugin_service.set_enabled(db, plugin_id, False)
    for tool in await plugin_service.list_tools(db):
        if tool.plugin_id == plugin_id:
            tool.enabled = False
    await sync_plugin_tools(db)
    await db.commit()
    return {"plugin": serialize_plugin(row)}


@router.get("/plugins/tools")
async def list_plugin_tools(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await plugin_service.list_tools(db)
    return {"tools": [serialize_plugin_tool(row) for row in rows]}


@router.post("/plugins/tools/{tool_id}/enable")
async def enable_plugin_tool(tool_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    try:
        tool = await plugin_service.set_tool_enabled(db, tool_id, True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await sync_plugin_tools(db)
    await db.commit()
    return {"tool": serialize_plugin_tool(tool)}


@router.post("/plugins/tools/{tool_id}/disable")
async def disable_plugin_tool(tool_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    tool = await plugin_service.set_tool_enabled(db, tool_id, False)
    await sync_plugin_tools(db)
    await db.commit()
    return {"tool": serialize_plugin_tool(tool)}


@router.get("/health/plugins")
async def plugins_health(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    plugins = await plugin_service.list_plugins(db)
    enabled = get_settings().plugins.enabled
    failed = [plugin for plugin in plugins if plugin.status == "failed"]
    if not enabled:
        status = "disabled"
    elif failed:
        status = "degraded"
    elif plugins:
        status = "ok"
    else:
        status = "none"
    return {
        "status": status,
        "enabled": enabled,
        "plugin_count": len(plugins),
        "failed_count": len(failed),
        "directory": str(get_settings().plugins.directory),
        "execution": "manifest_only",
    }
