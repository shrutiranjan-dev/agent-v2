from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data
from backend.app.db.models import Plugin, PluginTool
from backend.app.plugins.manifest import PluginManifest, load_manifest
from backend.app.runtime.event_bus import event_bus


def serialize_plugin(plugin: Plugin) -> dict[str, Any]:
    return {
        "id": str(plugin.id),
        "organization_id": str(plugin.organization_id) if plugin.organization_id else None,
        "project_id": str(plugin.project_id) if plugin.project_id else None,
        "workspace_id": str(plugin.workspace_id) if plugin.workspace_id else None,
        "name": plugin.name,
        "version": plugin.version,
        "manifest_path": plugin.manifest_path,
        "source_type": plugin.source_type,
        "status": plugin.status,
        "enabled": plugin.enabled,
        "trusted": plugin.trusted,
        "capabilities": plugin.capabilities_json,
        "hooks": plugin.hooks_json,
        "last_loaded_at": plugin.last_loaded_at.isoformat() if plugin.last_loaded_at else None,
        "last_error": plugin.last_error,
        "metadata": redact_data(plugin.metadata_json),
        "created_at": plugin.created_at.isoformat(),
        "updated_at": plugin.updated_at.isoformat(),
    }


def serialize_plugin_tool(tool: PluginTool) -> dict[str, Any]:
    return {
        "id": str(tool.id),
        "plugin_id": str(tool.plugin_id),
        "name": tool.name,
        "full_name": tool.full_name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "risk_level": tool.risk_level,
        "enabled": tool.enabled,
        "metadata": redact_data(tool.metadata_json),
        "created_at": tool.created_at.isoformat(),
        "updated_at": tool.updated_at.isoformat(),
    }


def plugin_tool_full_name(plugin_name: str, tool_name: str) -> str:
    from backend.app.mcp.service import safe_slug

    return f"plugin.{safe_slug(plugin_name)}.{safe_slug(tool_name)}"


@dataclass(slots=True)
class PluginLoadRequest:
    manifest_path: str
    organization_id: UUID | None = None
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    trusted: bool = False


class PluginService:
    async def load(self, db: AsyncSession, payload: PluginLoadRequest) -> Plugin:
        path = self._resolve_manifest_path(payload.manifest_path)
        try:
            manifest = load_manifest(path)
        except Exception as exc:
            # On a failed load, derive a stable, path-independent fallback
            # name from the resolved path. Using the raw input path can
            # produce unstable names across platforms (PosixPath sees a
            # Windows path like "C:\..." as a single component, giving a
            # different stem than on Windows) and the same name across
            # retries of the same path (which collides on the unique
            # (organization_id, name) constraint). Use the resolved path
            # and a short content hash so retries of the same manifest
            # path reuse the same failed-plugin row.
            resolved_str = str(path.resolve())
            digest = hashlib.sha256(resolved_str.encode("utf-8")).hexdigest()[:12]
            stem_source = path.name or "invalid-plugin"
            fallback_name = f"invalid-{stem_source}-{digest}"
            existing = await self._get_by_name(db, payload.organization_id, fallback_name)
            if existing is not None:
                existing.manifest_path = str(path)
                existing.last_error = str(exc)
                existing.status = "failed"
                existing.last_loaded_at = None
                await db.flush()
                await event_bus.publish(
                    db,
                    organization_id=payload.organization_id,
                    project_id=payload.project_id,
                    workspace_id=payload.workspace_id,
                    event_type=EventType.PLUGIN_FAILED,
                    severity="warning",
                    payload={"manifest_path": str(path), "error": str(exc)},
                )
                return existing
            plugin = Plugin(
                organization_id=payload.organization_id,
                project_id=payload.project_id,
                workspace_id=payload.workspace_id,
                name=fallback_name,
                manifest_path=str(path),
                source_type="local",
                status="failed",
                enabled=False,
                trusted=False,
                last_error=str(exc),
                metadata_json={},
            )
            db.add(plugin)
            await db.flush()
            await event_bus.publish(
                db,
                organization_id=payload.organization_id,
                project_id=payload.project_id,
                workspace_id=payload.workspace_id,
                event_type=EventType.PLUGIN_FAILED,
                severity="warning",
                payload={"manifest_path": str(path), "error": str(exc)},
            )
            return plugin

        plugin = await self._get_by_name(db, payload.organization_id, manifest.name)
        if not plugin:
            plugin = Plugin(
                organization_id=payload.organization_id,
                project_id=payload.project_id,
                workspace_id=payload.workspace_id,
                name=manifest.name,
            )
            db.add(plugin)
        plugin.version = manifest.version
        plugin.manifest_path = str(path)
        plugin.source_type = "local"
        plugin.status = "loaded"
        plugin.enabled = False
        plugin.trusted = payload.trusted
        plugin.capabilities_json = manifest.capabilities
        plugin.hooks_json = manifest.hooks
        plugin.last_loaded_at = datetime.now(UTC)
        plugin.last_error = None
        plugin.metadata_json = redact_data(manifest.metadata)
        await db.flush()
        await self._sync_tools(db, plugin=plugin, manifest=manifest)
        await event_bus.publish(
            db,
            organization_id=plugin.organization_id,
            project_id=plugin.project_id,
            workspace_id=plugin.workspace_id,
            event_type=EventType.PLUGIN_LOADED,
            payload={"plugin_id": str(plugin.id), "name": plugin.name, "tools": len(manifest.tools)},
        )
        return plugin

    def _resolve_manifest_path(self, manifest_path: str) -> Path:
        path = Path(manifest_path).expanduser()
        if not path.is_absolute():
            path = get_settings().plugins.directory / path
        return path.resolve()

    async def _get_by_name(self, db: AsyncSession, organization_id: UUID | None, name: str) -> Plugin | None:
        if hasattr(db, "objects"):
            for (model, _), row in db.objects.items():
                if model is Plugin and row.organization_id == organization_id and row.name == name:
                    return row
            return None
        return await db.scalar(
            select(Plugin).where(Plugin.organization_id == organization_id, Plugin.name == name)
        )

    async def _sync_tools(self, db: AsyncSession, *, plugin: Plugin, manifest: PluginManifest) -> None:
        for definition in manifest.tools:
            full_name = plugin_tool_full_name(plugin.name, definition.name)
            row = await self.get_tool_by_full_name(db, full_name)
            if not row:
                row = PluginTool(plugin_id=plugin.id, name=definition.name, full_name=full_name)
                db.add(row)
            row.description = definition.description
            row.input_schema = definition.input_schema or {"type": "object", "properties": {}}
            row.risk_level = definition.risk_level or "medium"
            row.enabled = bool(
                plugin.enabled and plugin.trusted and get_settings().plugins.auto_register_trusted_tools
            )
            row.metadata_json = redact_data(definition.metadata)
            await db.flush()
            await event_bus.publish(
                db,
                organization_id=plugin.organization_id,
                project_id=plugin.project_id,
                workspace_id=plugin.workspace_id,
                event_type=EventType.PLUGIN_TOOL_REGISTERED,
                payload={"tool": full_name, "enabled": row.enabled, "plugin_id": str(plugin.id)},
            )

    async def list_plugins(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[Plugin]:
        if hasattr(db, "objects"):
            rows = [row for (model, _), row in db.objects.items() if model is Plugin]
            return [
                row
                for row in rows
                if (organization_id is None or row.organization_id == organization_id)
                and (workspace_id is None or row.workspace_id in {None, workspace_id})
            ]
        stmt = select(Plugin).order_by(Plugin.created_at.desc())
        if organization_id:
            stmt = stmt.where(Plugin.organization_id == organization_id)
        if workspace_id:
            stmt = stmt.where((Plugin.workspace_id == workspace_id) | (Plugin.workspace_id.is_(None)))
        return list((await db.scalars(stmt)).all())

    async def list_tools(self, db: AsyncSession, *, enabled: bool | None = None) -> list[PluginTool]:
        if hasattr(db, "objects"):
            rows = [row for (model, _), row in db.objects.items() if model is PluginTool]
            return [row for row in rows if enabled is None or row.enabled == enabled]
        stmt = select(PluginTool).order_by(PluginTool.created_at.desc())
        if enabled is not None:
            stmt = stmt.where(PluginTool.enabled == enabled)
        return list((await db.scalars(stmt)).all())

    async def get_plugin(self, db: AsyncSession, plugin_id: UUID) -> Plugin:
        row = await db.get(Plugin, plugin_id)
        if not row:
            raise KeyError(f"Plugin not found: {plugin_id}")
        return row

    async def get_tool_by_full_name(self, db: AsyncSession, full_name: str) -> PluginTool | None:
        if hasattr(db, "objects"):
            for (model, _), row in db.objects.items():
                if model is PluginTool and row.full_name == full_name:
                    return row
            return None
        return await db.scalar(select(PluginTool).where(PluginTool.full_name == full_name))

    async def get_plugin_for_tool(self, db: AsyncSession, tool: PluginTool) -> Plugin:
        plugin = await db.get(Plugin, tool.plugin_id)
        if not plugin:
            raise KeyError(f"Plugin not found for tool: {tool.full_name}")
        return plugin

    async def set_enabled(self, db: AsyncSession, plugin_id: UUID, enabled: bool) -> Plugin:
        plugin = await self.get_plugin(db, plugin_id)
        plugin.enabled = enabled
        plugin.status = "loaded" if enabled else "disabled"
        plugin.updated_at = datetime.now(UTC)
        await db.flush()
        return plugin

    async def set_tool_enabled(self, db: AsyncSession, tool_id: UUID, enabled: bool) -> PluginTool:
        tool = await db.get(PluginTool, tool_id)
        if not tool:
            raise KeyError(f"Plugin tool not found: {tool_id}")
        plugin = await self.get_plugin_for_tool(db, tool)
        if enabled and (not plugin.enabled or not plugin.trusted):
            raise PermissionError("Plugin tool can only be enabled when its plugin is enabled and trusted.")
        tool.enabled = enabled
        tool.updated_at = datetime.now(UTC)
        await db.flush()
        return tool

    async def call_tool(self, db: AsyncSession, full_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = await self.get_tool_by_full_name(db, full_name)
        if not tool or not tool.enabled:
            raise PermissionError(f"Plugin tool is disabled or unknown: {full_name}")
        plugin = await self.get_plugin_for_tool(db, tool)
        if not plugin.enabled or not plugin.trusted:
            raise PermissionError(f"Plugin must be enabled and trusted before tool execution: {plugin.name}")
        if tool.name == "echo":
            return {"text": str(arguments.get("text", "")), "plugin": plugin.name}
        raise RuntimeError("Arbitrary plugin code execution is disabled in Batch 1.")


plugin_service = PluginService()
