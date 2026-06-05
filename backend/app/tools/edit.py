import difflib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    ensure_inside_workspace,
    file_sha256,
    resolve_workspace_path,
)
from backend.app.tools.write import atomic_write_text


class EditFileInput(BaseModel):
    path: str
    old: str | None = None
    new: str
    replace_all: bool = False
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    dry_run: bool = False
    expected_existing_hash: str | None = None

    @model_validator(mode="after")
    def validate_match_mode(self) -> "EditFileInput":
        if self.old is None and (self.start_line is None or self.end_line is None):
            raise ValueError("Either old text or start_line/end_line must be provided.")
        if self.start_line is not None and self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line.")
        return self


class EditFileTool(BaseTool):
    name = "edit.file"
    title = "Edit File"
    description = "Edit a UTF-8 workspace file by exact text replacement or line range replacement."
    category = "filesystem"
    input_model = EditFileInput
    permission_key = "edit.file"
    risk_level = "medium"
    timeout_seconds = 15
    examples = [
        {"path": "README.md", "old": "foo", "new": "bar"},
        {"path": "README.md", "start_line": 10, "end_line": 12, "new": "replacement\\n", "dry_run": True},
    ]

    def resource(self, input_data: EditFileInput, workspace_root: Path) -> str:
        return str(resolve_workspace_path(workspace_root, input_data.path))

    async def run(self, input_data: EditFileInput, ctx: ToolContext) -> ToolResult:
        target = resolve_workspace_path(ctx.workspace_root, input_data.path)
        ensure_inside_workspace(ctx.workspace_root, target, action="edit")
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {target}")
        if target.is_dir():
            raise IsADirectoryError(f"Path is a directory, not a file: {target}")

        before = target.read_text(encoding="utf-8")
        before_hash = file_sha256(target)
        if input_data.expected_existing_hash and before_hash != input_data.expected_existing_hash:
            return ToolResult.failure(
                code="stale_file_hash",
                message="Refusing to edit because expected_existing_hash does not match current file.",
                detail={"expected": input_data.expected_existing_hash, "actual": before_hash},
                recoverable=True,
                metadata={"path": input_data.path, "resolved_path": str(target)},
            )

        replacements = 1
        if input_data.start_line is not None and input_data.end_line is not None:
            lines = before.splitlines(keepends=True)
            if input_data.start_line > len(lines) + 1:
                return ToolResult.failure(
                    code="line_range_out_of_bounds",
                    message="start_line is beyond the end of the file.",
                    detail={"total_lines": len(lines), "start_line": input_data.start_line},
                    recoverable=True,
                )
            start = input_data.start_line - 1
            end = input_data.end_line
            replacement = input_data.new
            if replacement and not replacement.endswith("\n"):
                replacement += "\n"
            after = "".join([*lines[:start], replacement, *lines[end:]])
        else:
            assert input_data.old is not None
            count = before.count(input_data.old)
            if count == 0:
                return ToolResult.failure(
                    code="old_text_not_found",
                    message="Old text was not found in file.",
                    recoverable=True,
                    metadata={"path": input_data.path, "resolved_path": str(target)},
                )
            if count > 1 and not input_data.replace_all:
                return ToolResult.failure(
                    code="ambiguous_match",
                    message="Old text appears multiple times; set replace_all=true or provide a unique match.",
                    detail={"matches": count},
                    recoverable=True,
                    metadata={"path": input_data.path, "resolved_path": str(target)},
                )
            replacements = count if input_data.replace_all else 1
            after = before.replace(input_data.old, input_data.new, -1 if input_data.replace_all else 1)

        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=str(target),
                tofile=str(target),
            )
        )
        after_hash = None
        if not input_data.dry_run:
            atomic_write_text(target, after)
            after_hash = file_sha256(target)
        return ToolResult(
            title=str(target),
            output={
                "path": input_data.path,
                "resolved_path": str(target),
                "dry_run": input_data.dry_run,
                "replacements": replacements,
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "diff": diff,
            },
            metadata={
                "path": input_data.path,
                "resolved_path": str(target),
                "dry_run": input_data.dry_run,
                "replacements": replacements,
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "diff": diff,
            },
        )
