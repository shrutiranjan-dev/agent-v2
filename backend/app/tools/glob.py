import fnmatch
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    ensure_inside_workspace,
    is_inside,
    resolve_workspace_path,
)


class GlobSearchInput(BaseModel):
    pattern: str
    path: str | None = None
    include_hidden: bool = False
    exclude: list[str] = Field(default_factory=list)
    max_results: int = Field(default=100, ge=1, le=5000)
    kind: Literal["files", "directories", "both"] = "files"

    @field_validator("exclude", mode="before")
    @classmethod
    def split_patterns(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class GlobSearchTool(BaseTool):
    name = "glob.search"
    title = "Glob Search"
    description = "Find workspace files or directories using a rooted glob pattern."
    category = "search"
    input_model = GlobSearchInput
    permission_key = "glob.search"
    risk_level = "low"
    timeout_seconds = 10
    examples = [
        {"pattern": "**/*.py", "path": "backend/app"},
        {"pattern": ".*", "include_hidden": True, "kind": "both"},
    ]

    def resource(self, input_data: GlobSearchInput, workspace_root: Path) -> str:
        return str(resolve_workspace_path(workspace_root, input_data.path or "."))

    async def run(self, input_data: GlobSearchInput, ctx: ToolContext) -> ToolResult:
        workspace_root = ctx.workspace_root.resolve()
        root = resolve_workspace_path(workspace_root, input_data.path or ".")
        ensure_inside_workspace(workspace_root, root, action="glob")
        if root.is_file():
            raise ValueError(f"glob.search path must be a directory: {root}")
        if not root.exists():
            raise FileNotFoundError(f"glob.search path does not exist: {root}")

        results: list[Path] = []
        blocked_symlinks = 0
        for candidate in root.glob(input_data.pattern):
            resolved = candidate.resolve()
            if not is_inside(workspace_root, resolved):
                blocked_symlinks += 1
                continue
            rel = candidate.relative_to(workspace_root).as_posix()
            if not input_data.include_hidden and any(part.startswith(".") for part in candidate.relative_to(root).parts):
                continue
            if input_data.exclude and any(fnmatch.fnmatch(rel, pattern) for pattern in input_data.exclude):
                continue
            if input_data.kind == "files" and not candidate.is_file():
                continue
            if input_data.kind == "directories" and not candidate.is_dir():
                continue
            results.append(candidate)

        results.sort(key=lambda path: path.as_posix())
        truncated = len(results) > input_data.max_results
        visible = results[: input_data.max_results]
        payload = [
            {
                "path": str(path),
                "relative_path": path.relative_to(workspace_root).as_posix(),
                "kind": "directory" if path.is_dir() else "file",
            }
            for path in visible
        ]
        return ToolResult(
            title=str(root),
            output={
                "results": payload,
                "count": len(results),
                "truncated": truncated,
                "blocked_symlinks": blocked_symlinks,
            },
            metadata={"count": len(results), "truncated": truncated, "blocked_symlinks": blocked_symlinks},
            truncated=truncated,
        )
