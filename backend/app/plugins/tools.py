from __future__ import annotations

from typing import Any

from backend.app.core.redaction import redact_data
from backend.app.mcp.tools import ExternalJsonInput, validate_json_schema_subset
from backend.app.plugins.service import plugin_service
from backend.app.tools.base import BaseTool, ToolContext, ToolResult


class PluginManifestTool(BaseTool):
    category = "plugin"
    requires_workspace = False
    supports_artifacts = False
    input_model = ExternalJsonInput

    def __init__(
        self,
        *,
        name: str,
        description: str | None,
        input_schema: dict[str, Any],
        risk_level: str,
        enabled: bool,
    ) -> None:
        self.name = name
        self.title = name
        self.description = description or f"Plugin tool {name}"
        self.permission_key = name
        self.risk_level = risk_level or "medium"
        self.enabled = enabled
        self._input_schema = input_schema or {"type": "object", "properties": {}}

    def schema(self) -> dict[str, Any]:
        base = super().schema()
        base["input_schema"] = self._input_schema
        return base

    async def run(self, input_data: ExternalJsonInput, ctx: ToolContext) -> ToolResult:
        payload = dict(input_data.model_extra or {})
        validation_error = validate_json_schema_subset(self._input_schema, payload)
        if validation_error:
            return ToolResult.failure(code="plugin_input_invalid", message=validation_error, recoverable=True)
        if ctx.db is None:
            return ToolResult.failure(
                code="plugin_db_required",
                message="Plugin tool execution requires a database-backed context.",
                recoverable=True,
            )
        try:
            result = await plugin_service.call_tool(ctx.db, self.name, payload)
        except Exception as exc:
            return ToolResult.failure(
                code="plugin_tool_failed",
                message=str(exc),
                recoverable=True,
                metadata={"tool": self.name},
            )
        return ToolResult(
            title=f"Plugin tool {self.name}",
            output=redact_data(result),
            metadata={"tool": self.name, "source": "plugin"},
        )
