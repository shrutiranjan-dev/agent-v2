from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.app.core.redaction import redact_data
from backend.app.mcp.service import mcp_service
from backend.app.tools.base import BaseTool, ToolContext, ToolResult


class ExternalJsonInput(BaseModel):
    model_config = ConfigDict(extra="allow")


def validate_json_schema_subset(schema: dict[str, Any], payload: dict[str, Any]) -> str | None:
    required = schema.get("required") if isinstance(schema, dict) else None
    if isinstance(required, list):
        missing = [item for item in required if item not in payload]
        if missing:
            return f"Missing required field(s): {', '.join(map(str, missing))}"
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if isinstance(properties, dict):
        for key, spec in properties.items():
            if key not in payload or not isinstance(spec, dict):
                continue
            expected = spec.get("type")
            value = payload[key]
            if expected == "string" and not isinstance(value, str):
                return f"Field {key} must be a string."
            if expected == "number" and not isinstance(value, int | float):
                return f"Field {key} must be a number."
            if expected == "integer" and not isinstance(value, int):
                return f"Field {key} must be an integer."
            if expected == "boolean" and not isinstance(value, bool):
                return f"Field {key} must be a boolean."
            if expected == "array" and not isinstance(value, list):
                return f"Field {key} must be an array."
            if expected == "object" and not isinstance(value, dict):
                return f"Field {key} must be an object."
    return None


class McpWrappedTool(BaseTool):
    category = "mcp"
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
        self.description = description or f"MCP tool {name}"
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
            return ToolResult.failure(code="mcp_input_invalid", message=validation_error, recoverable=True)
        if ctx.db is None:
            return ToolResult.failure(
                code="mcp_db_required",
                message="MCP tool execution requires a database-backed context.",
                recoverable=True,
            )
        try:
            result = await mcp_service.call_tool(ctx.db, self.name, payload)
        except Exception as exc:
            return ToolResult.failure(
                code="mcp_tool_failed",
                message=str(exc),
                recoverable=True,
                metadata={"tool": self.name},
            )
        return ToolResult(
            title=f"MCP tool {self.name}",
            output=redact_data(result),
            metadata={"tool": self.name, "source": "mcp"},
        )
