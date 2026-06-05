from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data
from backend.app.db.models import McpServer, McpTool
from backend.app.mcp.client import McpToolDefinition, mcp_client
from backend.app.runtime.event_bus import event_bus


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()
    return slug or "unnamed"


def serialize_mcp_server(server: McpServer) -> dict[str, Any]:
    return {
        "id": str(server.id),
        "organization_id": str(server.organization_id) if server.organization_id else None,
        "project_id": str(server.project_id) if server.project_id else None,
        "workspace_id": str(server.workspace_id) if server.workspace_id else None,
        "name": server.name,
        "server_type": server.server_type,
        "command": server.command,
        "args": server.args_json,
        "cwd": server.cwd,
        "url": server.url,
        "env": redact_data(server.env_json),
        "status": server.status,
        "enabled": server.enabled,
        "trusted": server.trusted,
        "last_connected_at": server.last_connected_at.isoformat() if server.last_connected_at else None,
        "last_error": server.last_error,
        "metadata": redact_data(server.metadata_json),
        "created_at": server.created_at.isoformat(),
        "updated_at": server.updated_at.isoformat(),
    }


def serialize_mcp_tool(tool: McpTool) -> dict[str, Any]:
    return {
        "id": str(tool.id),
        "mcp_server_id": str(tool.mcp_server_id),
        "name": tool.name,
        "full_name": tool.full_name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "risk_level": tool.risk_level,
        "enabled": tool.enabled,
        "discovered_at": tool.discovered_at.isoformat() if tool.discovered_at else None,
        "metadata": redact_data(tool.metadata_json),
        "created_at": tool.created_at.isoformat(),
        "updated_at": tool.updated_at.isoformat(),
    }


@dataclass(slots=True)
class McpServerCreate:
    name: str
    server_type: str
    organization_id: UUID | None = None
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    url: str | None = None
    env: dict[str, Any] = field(default_factory=dict)
    enabled: bool = False
    trusted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class McpService:
    async def create_server(self, db: AsyncSession, payload: McpServerCreate) -> McpServer:
        server = McpServer(
            organization_id=payload.organization_id,
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            name=payload.name,
            server_type=payload.server_type,
            command=payload.command,
            args_json=payload.args,
            cwd=payload.cwd,
            url=payload.url,
            env_json=redact_data(payload.env),
            enabled=payload.enabled,
            trusted=payload.trusted,
            status="configured" if payload.enabled else "disabled",
            metadata_json=redact_data(payload.metadata),
        )
        db.add(server)
        await db.flush()
        return server

    async def list_servers(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[McpServer]:
        if hasattr(db, "objects"):
            rows = [row for (model, _), row in db.objects.items() if model is McpServer]
            return [
                row
                for row in rows
                if (organization_id is None or row.organization_id == organization_id)
                and (workspace_id is None or row.workspace_id in {None, workspace_id})
            ]
        stmt = select(McpServer).order_by(McpServer.created_at.desc())
        if organization_id:
            stmt = stmt.where(McpServer.organization_id == organization_id)
        if workspace_id:
            stmt = stmt.where((McpServer.workspace_id == workspace_id) | (McpServer.workspace_id.is_(None)))
        return list((await db.scalars(stmt)).all())

    async def list_tools(
        self,
        db: AsyncSession,
        *,
        enabled: bool | None = None,
    ) -> list[McpTool]:
        if hasattr(db, "objects"):
            rows = [row for (model, _), row in db.objects.items() if model is McpTool]
            return [row for row in rows if enabled is None or row.enabled == enabled]
        stmt = select(McpTool).order_by(McpTool.created_at.desc())
        if enabled is not None:
            stmt = stmt.where(McpTool.enabled == enabled)
        return list((await db.scalars(stmt)).all())

    async def get_server(self, db: AsyncSession, server_id: UUID) -> McpServer:
        row = await db.get(McpServer, server_id)
        if not row:
            raise KeyError(f"MCP server not found: {server_id}")
        return row

    async def get_tool_by_full_name(self, db: AsyncSession, full_name: str) -> McpTool | None:
        if hasattr(db, "objects"):
            for (model, _), row in db.objects.items():
                if model is McpTool and row.full_name == full_name:
                    return row
            return None
        return await db.scalar(select(McpTool).where(McpTool.full_name == full_name))

    async def get_server_for_tool(self, db: AsyncSession, tool: McpTool) -> McpServer:
        server = await db.get(McpServer, tool.mcp_server_id)
        if not server:
            raise KeyError(f"MCP server not found for tool: {tool.full_name}")
        return server

    async def set_enabled(self, db: AsyncSession, server_id: UUID, enabled: bool) -> McpServer:
        server = await self.get_server(db, server_id)
        server.enabled = enabled
        server.status = "configured" if enabled else "disabled"
        server.updated_at = datetime.now(UTC)
        await db.flush()
        return server

    async def disconnect(self, db: AsyncSession, server_id: UUID) -> McpServer:
        server = await self.get_server(db, server_id)
        status = await mcp_client.disconnect(server)
        server.status = "configured" if server.enabled else "disabled"
        server.last_error = None if status.status == "disconnected" else status.reason
        server.updated_at = datetime.now(UTC)
        await db.flush()
        return server

    async def connect(self, db: AsyncSession, server_id: UUID) -> McpServer:
        server = await self.get_server(db, server_id)
        if not server.enabled:
            server.status = "disabled"
            server.last_error = "MCP server is disabled."
            await db.flush()
            return server
        server.status = "connecting"
        await db.flush()
        status = await mcp_client.connect(server)
        if status.status in {"available", "connected"}:
            server.status = "connected"
            server.last_connected_at = datetime.now(UTC)
            server.last_error = None
            event_type = EventType.MCP_SERVER_CONNECTED
            severity = "info"
        else:
            server.status = "failed" if status.status == "failed" else status.status
            server.last_error = status.reason
            event_type = EventType.MCP_SERVER_FAILED
            severity = "warning"
        await event_bus.publish(
            db,
            organization_id=server.organization_id,
            project_id=server.project_id,
            workspace_id=server.workspace_id,
            event_type=event_type,
            severity=severity,
            payload={"server_id": str(server.id), "name": server.name, "status": server.status, "error": server.last_error},
        )
        await db.flush()
        return server

    async def discover_tools(self, db: AsyncSession, server_id: UUID) -> list[McpTool]:
        server = await self.get_server(db, server_id)
        try:
            definitions = await mcp_client.discover_tools(server)
        except Exception as exc:
            server.status = "failed"
            server.last_error = str(exc)
            await event_bus.publish(
                db,
                organization_id=server.organization_id,
                project_id=server.project_id,
                workspace_id=server.workspace_id,
                event_type=EventType.MCP_SERVER_FAILED,
                severity="warning",
                payload={"server_id": str(server.id), "name": server.name, "error": server.last_error},
            )
            await db.flush()
            return []

        rows: list[McpTool] = []
        for definition in definitions:
            rows.append(await self.upsert_tool(db, server=server, definition=definition))
        await event_bus.publish(
            db,
            organization_id=server.organization_id,
            project_id=server.project_id,
            workspace_id=server.workspace_id,
            event_type=EventType.MCP_TOOLS_DISCOVERED,
            payload={"server_id": str(server.id), "name": server.name, "count": len(rows)},
        )
        return rows

    async def upsert_tool(
        self,
        db: AsyncSession,
        *,
        server: McpServer,
        definition: McpToolDefinition,
    ) -> McpTool:
        full_name = f"mcp.{safe_slug(server.name)}.{safe_slug(definition.name)}"
        row = await self.get_tool_by_full_name(db, full_name)
        if not row:
            row = McpTool(
                mcp_server_id=server.id,
                name=definition.name,
                full_name=full_name,
                enabled=False,
            )
            db.add(row)
        row.description = definition.description
        row.input_schema = definition.input_schema or {"type": "object", "properties": {}}
        row.risk_level = definition.risk_level or "medium"
        row.discovered_at = datetime.now(UTC)
        row.metadata_json = redact_data(definition.metadata or {})
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=server.organization_id,
            project_id=server.project_id,
            workspace_id=server.workspace_id,
            event_type=EventType.MCP_TOOL_REGISTERED,
            payload={"tool": full_name, "enabled": row.enabled, "server_id": str(server.id)},
        )
        return row

    async def set_tool_enabled(self, db: AsyncSession, tool_id: UUID, enabled: bool) -> McpTool:
        tool = await db.get(McpTool, tool_id)
        if not tool:
            raise KeyError(f"MCP tool not found: {tool_id}")
        server = await self.get_server_for_tool(db, tool)
        if enabled and (not server.enabled or not server.trusted):
            raise PermissionError("MCP tool can only be enabled when its server is enabled and trusted.")
        tool.enabled = enabled
        tool.updated_at = datetime.now(UTC)
        await db.flush()
        return tool

    async def call_tool(self, db: AsyncSession, full_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = await self.get_tool_by_full_name(db, full_name)
        if not tool or not tool.enabled:
            raise PermissionError(f"MCP tool is disabled or unknown: {full_name}")
        server = await self.get_server_for_tool(db, tool)
        if not server.enabled or not server.trusted:
            raise PermissionError(f"MCP server must be enabled and trusted before tool execution: {server.name}")
        return await mcp_client.call_tool(server, tool.name, arguments)


mcp_service = McpService()
