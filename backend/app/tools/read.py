from pathlib import Path

from pydantic import BaseModel, Field

from backend.app.core.redaction import REDACTED, redact_text
from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    ensure_inside_workspace,
    looks_binary,
    resolve_workspace_path,
)


class ReadFileInput(BaseModel):
    path: str
    offset: int = Field(default=1, ge=1)
    limit: int = Field(default=2000, ge=1, le=5000)
    max_bytes: int = Field(default=51200, ge=1, le=262144)
    line_numbers: bool = True
    encoding: str = "utf-8"


class ReadFileTool(BaseTool):
    name = "read.file"
    title = "Read File"
    description = "Read a workspace text file or list a directory with line ranges, byte caps, and redaction."
    category = "filesystem"
    input_model = ReadFileInput
    permission_key = "read.file"
    risk_level = "low"
    timeout_seconds = 10
    max_output_chars = 60000
    examples = [
        {"path": "README.md"},
        {"path": "backend/app/main.py", "offset": 1, "limit": 80},
    ]

    def resource(self, input_data: ReadFileInput, workspace_root: Path) -> str:
        return str(resolve_workspace_path(workspace_root, input_data.path))

    async def run(self, input_data: ReadFileInput, ctx: ToolContext) -> ToolResult:
        target = resolve_workspace_path(ctx.workspace_root, input_data.path)
        ensure_inside_workspace(ctx.workspace_root, target, action="read")
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {target}")
        if target.is_dir():
            entries = sorted(
                [entry.name + ("/" if entry.is_dir() else "") for entry in target.iterdir()],
                key=lambda name: (not name.endswith("/"), name.lower()),
            )
            output = "\n".join(entries) if entries else "(empty directory)"
            return ToolResult(
                title=str(target),
                output=output,
                metadata={
                    "type": "directory",
                    "path": input_data.path,
                    "resolved_path": str(target),
                    "count": len(entries),
                },
            )

        data = target.read_bytes()
        if looks_binary(data[: min(len(data), 8192)]):
            return ToolResult.failure(
                code="binary_file_refused",
                message=f"Refusing to read binary file: {target}",
                recoverable=False,
                metadata={"path": input_data.path, "resolved_path": str(target), "bytes": len(data)},
            )

        truncated_by_bytes = len(data) > input_data.max_bytes
        data = data[: input_data.max_bytes]
        try:
            text = data.decode(input_data.encoding)
            encoding_used = input_data.encoding
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            encoding_used = "utf-8-replace"

        lines = text.splitlines()
        start = input_data.offset - 1
        end = min(start + input_data.limit, len(lines))
        selected = lines[start:end]
        if input_data.line_numbers:
            content = "\n".join(f"{idx + 1}: {line}" for idx, line in enumerate(selected, start=start))
        else:
            content = "\n".join(selected)
        redacted_content = redact_text(content)
        redacted = redacted_content != content or REDACTED in redacted_content
        truncated = truncated_by_bytes or end < len(lines)
        return ToolResult(
            title=str(target),
            output={
                "path": input_data.path,
                "resolved_path": str(target),
                "content": redacted_content,
                "line_start": input_data.offset,
                "line_end": end,
                "total_lines": len(lines),
                "truncated": truncated,
            },
            metadata={
                "type": "file",
                "path": input_data.path,
                "resolved_path": str(target),
                "encoding": encoding_used,
                "line_start": input_data.offset,
                "line_end": end,
                "total_lines": len(lines),
                "bytes_read": len(data),
                "truncated": truncated,
            },
            redacted=redacted,
            truncated=truncated,
        )
