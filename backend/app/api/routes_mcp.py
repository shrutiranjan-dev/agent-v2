from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.core.config import get_settings
from backend.app.core.errors import NotFoundError
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.models import Session
from backend.app.db.postgres import get_session
from backend.app.mcp.client import mcp_client
from backend.app.mcp.registry import sync_mcp_tools
from backend.app.mcp.service import (
    McpServerCreate,
    mcp_service,
    serialize_mcp_server,
    serialize_mcp_tool,
)
from backend.app.runtime.tenant import ensure_runtime_tenant
from backend.app.runtime.tool_executor import ToolExecutor

router = APIRouter(tags=["mcp"])


class McpServerCreateRequest(BaseModel):
    name: str
    server_type: str = Field(pattern="^(stdio|http|sse)$")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    url: str | None = None
    env: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    trusted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpTestToolExecuteRequest(BaseModel):
    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)


@router.get("/mcp/servers")
async def list_mcp_servers(
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    rows = await mcp_service.list_servers(
        db,
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
    )
    return {"servers": [serialize_mcp_server(row) for row in rows]}


@router.post("/mcp/servers")
async def create_mcp_server(
    payload: McpServerCreateRequest,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    row = await mcp_service.create_server(
        db,
        McpServerCreate(
            organization_id=tenant.organization_id,
            project_id=tenant.project_id,
            workspace_id=tenant.workspace_id,
            name=payload.name,
            server_type=payload.server_type,
            command=payload.command,
            args=payload.args,
            cwd=payload.cwd,
            url=payload.url,
            env=payload.env,
            enabled=payload.enabled,
            trusted=payload.trusted,
            metadata=payload.metadata,
        ),
    )
    await db.commit()
    return {"server": serialize_mcp_server(row)}


@router.post("/mcp/servers/{server_id}/enable")
async def enable_mcp_server(server_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await mcp_service.set_enabled(db, server_id, True)
    await db.commit()
    return {"server": serialize_mcp_server(row)}


@router.post("/mcp/servers/{server_id}/disable")
async def disable_mcp_server(server_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await mcp_service.set_enabled(db, server_id, False)
    await sync_mcp_tools(db)
    await db.commit()
    return {"server": serialize_mcp_server(row)}


@router.post("/mcp/servers/{server_id}/connect")
async def connect_mcp_server(server_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await mcp_service.connect(db, server_id)
    await db.commit()
    return {"server": serialize_mcp_server(row)}


@router.post("/mcp/servers/{server_id}/disconnect")
async def disconnect_mcp_server(server_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await mcp_service.disconnect(db, server_id)
    await db.commit()
    return {"server": serialize_mcp_server(row)}


@router.post("/mcp/servers/{server_id}/discover")
async def discover_mcp_tools(server_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await mcp_service.discover_tools(db, server_id)
    await sync_mcp_tools(db)
    await db.commit()
    return {"tools": [serialize_mcp_tool(row) for row in rows]}


@router.get("/mcp/tools")
async def list_mcp_tools(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await mcp_service.list_tools(db)
    return {"tools": [serialize_mcp_tool(row) for row in rows]}


@router.post("/mcp/tools/{tool_id}/enable")
async def enable_mcp_tool(tool_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    try:
        row = await mcp_service.set_tool_enabled(db, tool_id, True)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await sync_mcp_tools(db)
    await db.commit()
    return {"tool": serialize_mcp_tool(row)}


@router.post("/mcp/tools/{tool_id}/disable")
async def disable_mcp_tool(tool_id: UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await mcp_service.set_tool_enabled(db, tool_id, False)
    await sync_mcp_tools(db)
    await db.commit()
    return {"tool": serialize_mcp_tool(row)}


@router.get("/health/mcp")
async def mcp_health(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    servers = await mcp_service.list_servers(db)
    sdk = mcp_client.sdk_status()
    enabled = get_settings().mcp.enabled
    if not enabled:
        status = "disabled"
    elif any(server.status == "connected" for server in servers):
        status = "ok"
    elif servers:
        status = "degraded"
    else:
        status = "none"
    return {
        "status": status,
        "enabled": enabled,
        "real_mcp": bool(sdk.real_sdk_available and sdk.stdio_available),
        "sdk_status": sdk.status,
        "stdio_transport": sdk.stdio_available,
        "http_transport": sdk.http_available,
        "sse_transport": sdk.sse_available,
        "reason": sdk.reason,
        "server_count": len(servers),
        "connected_servers": sum(1 for server in servers if server.status == "connected"),
        "failed_servers": sum(1 for server in servers if server.status == "failed"),
    }


@router.post("/mcp/test/execute-tool")
async def execute_mcp_tool_through_runtime(
    payload: McpTestToolExecuteRequest,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    settings = get_settings()
    if settings.app.env.lower() == "production" or not settings.app.enable_test_endpoints:
        raise NotFoundError("MCP test execution endpoint is disabled.")
    await sync_mcp_tools(db)
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    session = Session(
        organization_id=tenant.organization_id,
        project_id=tenant.project_id,
        workspace_id=tenant.workspace_id,
        created_by_user_id=tenant.user_id,
        title="MCP runtime smoke",
        agent_id="test",
        model_provider="ollama",
        model_name="local",
        status="idle",
    )
    db.add(session)
    await db.flush()
    agent = AgentDefinition(
        id="test",
        name="Test",
        description="MCP runtime smoke agent",
        mode="subagent",
        model_config=ModelConfig(model="local"),
        system_prompt="Test agent for guarded runtime smoke only.",
        allowed_tools=[payload.tool_name],
        permission_profile="test",
    )
    outcome = await ToolExecutor().execute(
        db,
        organization_id=tenant.organization_id,
        project_id=tenant.project_id,
        workspace_id=tenant.workspace_id,
        session_id=session.id,
        user_id=tenant.user_id,
        agent_run_id=None,
        agent=agent,
        tool_name=payload.tool_name,
        input_json=payload.input,
    )
    await db.commit()
    return {
        "status": outcome.status,
        "tool_call_id": str(outcome.tool_call.id),
        "permission_request_id": str(outcome.permission_request_id) if outcome.permission_request_id else None,
        "error": outcome.error,
    }
