from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from backend.app.core.config import get_settings
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import McpServer
from backend.app.tools.base import is_inside


@dataclass(slots=True)
class McpConnectionStatus:
    status: str
    reason: str | None = None
    real_sdk_available: bool = False
    stdio_available: bool = False
    http_available: bool = False
    sse_available: bool = False


@dataclass(slots=True)
class McpToolDefinition:
    name: str
    description: str | None
    input_schema: dict[str, Any]
    risk_level: str = "medium"
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class _SdkImports:
    client_session: Any
    stdio_params: Any
    stdio_client: Any


@dataclass(slots=True)
class _StdioLaunch:
    command: str
    args: list[str]
    env: dict[str, str]
    cwd: Path


class McpClient:
    """MCP lifecycle facade with real stdio transport.

    Batch 1 uses short-lived stdio sessions for connect/discovery/tool calls. That keeps
    process shutdown deterministic and avoids claiming a durable connection pool before
    the worker/runtime lifecycle needs it.
    """

    def _load_sdk(self) -> _SdkImports | None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception:
            return None
        return _SdkImports(
            client_session=ClientSession,
            stdio_params=StdioServerParameters,
            stdio_client=stdio_client,
        )

    def sdk_status(self) -> McpConnectionStatus:
        sdk = self._load_sdk()
        if sdk is None:
            return McpConnectionStatus(
                status="degraded",
                reason="Python MCP SDK is not installed; install with `pip install mcp`.",
                real_sdk_available=False,
                stdio_available=False,
            )
        return McpConnectionStatus(
            status="available",
            real_sdk_available=True,
            stdio_available=True,
            reason=None,
        )

    async def connect(self, server: McpServer) -> McpConnectionStatus:
        if not get_settings().mcp.enabled:
            return McpConnectionStatus(status="disabled", reason="MCP integration is disabled by config.")
        if not server.enabled:
            return McpConnectionStatus(status="disabled", reason="MCP server is disabled.")

        if server.server_type == "stdio":
            try:
                await self._with_stdio_session(server, lambda _session: self._noop())
            except Exception as exc:
                sdk = self.sdk_status()
                return McpConnectionStatus(
                    status="failed",
                    reason=redact_text(str(exc)),
                    real_sdk_available=sdk.real_sdk_available,
                    stdio_available=sdk.stdio_available,
                )
            sdk = self.sdk_status()
            return McpConnectionStatus(
                status="connected",
                real_sdk_available=sdk.real_sdk_available,
                stdio_available=sdk.stdio_available,
            )

        if server.server_type in {"http", "sse"}:
            if not server.url:
                return McpConnectionStatus(status="failed", reason=f"{server.server_type} MCP server is missing url.")
            try:
                async with httpx.AsyncClient(timeout=get_settings().mcp.connect_timeout_seconds) as client:
                    response = await client.get(server.url)
                    if response.status_code >= 500:
                        return McpConnectionStatus(
                            status="failed",
                            reason=f"MCP endpoint returned HTTP {response.status_code}.",
                        )
            except Exception as exc:
                return McpConnectionStatus(status="failed", reason=redact_text(str(exc)))
            sdk = self.sdk_status()
            if not sdk.real_sdk_available:
                return sdk
            return McpConnectionStatus(
                status="degraded",
                reason="HTTP/SSE MCP protocol transport is not wired in this batch.",
                real_sdk_available=True,
                stdio_available=sdk.stdio_available,
            )

        return McpConnectionStatus(status="failed", reason=f"Unsupported MCP server type: {server.server_type}")

    async def disconnect(self, server: McpServer) -> McpConnectionStatus:
        if server.server_type != "stdio":
            return McpConnectionStatus(status="disconnected", reason="No persistent MCP connection is held.")
        sdk = self.sdk_status()
        return McpConnectionStatus(
            status="disconnected",
            reason="Short-lived stdio sessions are closed after each operation.",
            real_sdk_available=sdk.real_sdk_available,
            stdio_available=sdk.stdio_available,
        )

    async def discover_tools(self, server: McpServer) -> list[McpToolDefinition]:
        if server.server_type != "stdio":
            status = await self.connect(server)
            raise RuntimeError(status.reason or f"MCP discovery is not wired for transport: {server.server_type}")

        async def _discover(session: Any) -> list[McpToolDefinition]:
            result = await session.list_tools()
            definitions: list[McpToolDefinition] = []
            for tool in getattr(result, "tools", []) or []:
                input_schema = (
                    getattr(tool, "inputSchema", None)
                    or getattr(tool, "input_schema", None)
                    or {"type": "object", "properties": {}}
                )
                if hasattr(input_schema, "model_dump"):
                    input_schema = input_schema.model_dump(mode="json")
                definitions.append(
                    McpToolDefinition(
                        name=str(getattr(tool, "name", "")),
                        description=getattr(tool, "description", None),
                        input_schema=input_schema if isinstance(input_schema, dict) else {},
                        risk_level=self._risk_from_tool(tool),
                        metadata=redact_data(self._jsonable(tool)),
                    )
                )
            return definitions

        return await self._with_stdio_session(server, _discover)

    async def call_tool(self, server: McpServer, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server.server_type != "stdio":
            raise RuntimeError(f"MCP tool calls are not wired for transport: {server.server_type}")

        async def _call(session: Any) -> dict[str, Any]:
            result = await session.call_tool(
                tool_name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=get_settings().mcp.call_timeout_seconds),
            )
            return self._normalize_call_result(result)

        return await self._with_stdio_session(server, _call)

    async def _with_stdio_session(
        self,
        server: McpServer,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        sdk = self._load_sdk()
        if sdk is None:
            raise RuntimeError("Python MCP SDK is not installed; install with `pip install mcp`.")
        launch = self._prepare_stdio_launch(server)
        errlog = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        params = sdk.stdio_params(
            command=launch.command,
            args=launch.args,
            env=launch.env,
            cwd=launch.cwd,
        )
        settings = get_settings()
        total_timeout = settings.mcp.connect_timeout_seconds + settings.mcp.call_timeout_seconds
        try:
            try:
                async with asyncio.timeout(total_timeout):
                    async with sdk.stdio_client(params, errlog=errlog) as (read_stream, write_stream):
                        async with sdk.client_session(
                            read_stream,
                            write_stream,
                            read_timeout_seconds=timedelta(seconds=settings.mcp.call_timeout_seconds),
                        ) as session:
                            await session.initialize()
                            return await operation(session)
            except TimeoutError as exc:
                raise TimeoutError(f"MCP stdio operation timed out after {total_timeout}s.") from exc
            except Exception as exc:
                errlog.seek(0)
                stderr = errlog.read().strip()
                message = str(exc)
                if stderr:
                    message = f"{message}; stderr={redact_text(stderr)}"
                raise RuntimeError(redact_text(message)) from exc
        finally:
            errlog.close()

    async def _noop(self) -> dict[str, str]:
        return {"ok": "true"}

    def _prepare_stdio_launch(self, server: McpServer) -> _StdioLaunch:
        settings = get_settings()
        if not server.command:
            raise RuntimeError("stdio MCP server is missing command.")
        raw_command = server.command
        command_name = Path(raw_command).name
        allowed = set(settings.mcp.allowed_stdio_commands)
        looks_like_path = Path(raw_command).is_absolute() or any(sep in raw_command for sep in ("/", "\\"))
        if (
            not server.trusted
            and not settings.mcp.allow_untrusted_stdio
            and looks_like_path
            and raw_command not in allowed
            and command_name not in allowed
        ):
            raise PermissionError(f"Untrusted stdio MCP command is not allowed: {command_name}")
        command = self._resolve_command(raw_command)
        if (
            not server.trusted
            and not settings.mcp.allow_untrusted_stdio
            and raw_command not in allowed
            and command_name not in allowed
            and command not in allowed
        ):
            raise PermissionError(f"Untrusted stdio MCP command is not allowed: {command_name}")
        cwd = self._resolve_cwd(getattr(server, "cwd", None), trusted=bool(server.trusted))
        return _StdioLaunch(
            command=command,
            args=[str(item) for item in (server.args_json or [])],
            env=self._build_env(server.env_json or {}),
            cwd=cwd,
        )

    def _resolve_command(self, command: str) -> str:
        candidate = Path(command).expanduser()
        if candidate.is_absolute():
            if not candidate.exists():
                raise RuntimeError(f"stdio MCP command not found: {command}")
            return str(candidate)
        resolved = shutil.which(command)
        if resolved is None:
            raise RuntimeError(f"stdio MCP command not found: {command}")
        return resolved

    def _resolve_cwd(self, cwd: str | None, *, trusted: bool) -> Path:
        settings = get_settings()
        workspace_root = settings.workspace_root.resolve()
        raw = Path(cwd).expanduser() if cwd else workspace_root
        resolved = raw if raw.is_absolute() else workspace_root / raw
        resolved = resolved.resolve()
        if not trusted and not is_inside(workspace_root, resolved):
            raise PermissionError(f"Untrusted stdio MCP cwd is outside workspace root: {resolved}")
        if not resolved.exists() or not resolved.is_dir():
            raise RuntimeError(f"stdio MCP cwd does not exist or is not a directory: {resolved}")
        return resolved

    def _build_env(self, configured_env: dict[str, Any]) -> dict[str, str]:
        settings = get_settings()
        env: dict[str, str] = {"PYTHONUNBUFFERED": "1"}
        for key in settings.mcp.env_allowlist:
            if key in os.environ:
                env[key] = os.environ[key]
        for key, value in configured_env.items():
            if value is None or value == "[REDACTED]":
                continue
            env[str(key)] = str(value)
        return env

    def _risk_from_tool(self, tool: Any) -> str:
        metadata = self._jsonable(tool)
        if isinstance(metadata, dict):
            annotations = metadata.get("annotations") or {}
            if isinstance(annotations, dict) and annotations.get("destructiveHint") is True:
                return "destructive"
            if isinstance(annotations, dict) and annotations.get("readOnlyHint") is True:
                return "low"
        return "medium"

    def _normalize_call_result(self, result: Any) -> dict[str, Any]:
        payload = redact_data(self._jsonable(result))
        serialized = json.dumps(payload, default=str, sort_keys=True)
        truncated = False
        if len(serialized) > get_settings().mcp.max_response_chars:
            payload = {"content": serialized[: get_settings().mcp.max_response_chars], "truncated": True}
            truncated = True
        if isinstance(payload, dict):
            payload.setdefault("truncated", truncated)
            payload.setdefault("is_error", bool(getattr(result, "isError", False) or getattr(result, "is_error", False)))
        return payload if isinstance(payload, dict) else {"content": payload, "truncated": truncated}

    def _jsonable(self, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list | tuple | set):
            return [self._jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._jsonable(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "__dict__"):
            return {
                str(key): self._jsonable(item)
                for key, item in vars(value).items()
                if not str(key).startswith("_")
            }
        return str(value)


mcp_client = McpClient()
