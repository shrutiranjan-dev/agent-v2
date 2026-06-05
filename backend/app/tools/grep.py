import fnmatch
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from backend.app.core.redaction import redact_text
from backend.app.permissions.models import PermissionAction
from backend.app.permissions.policy import evaluate_default_policy
from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    ensure_inside_workspace,
    looks_binary,
    resolve_workspace_path,
)


class GrepSearchInput(BaseModel):
    pattern: str
    path: str | None = None
    literal: bool = False
    case_sensitive: bool = True
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    max_matches: int = Field(default=100, ge=1, le=1000)
    max_files: int = Field(default=200, ge=1, le=5000)
    context_before: int = Field(default=0, ge=0, le=10)
    context_after: int = Field(default=0, ge=0, le=10)

    @field_validator("include", "exclude", mode="before")
    @classmethod
    def split_patterns(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class GrepSearchTool(BaseTool):
    name = "grep.search"
    title = "Grep Search"
    description = "Search workspace file contents with literal or regex matching, globs, context, and secret filtering."
    category = "search"
    input_model = GrepSearchInput
    permission_key = "grep.search"
    risk_level = "low"
    timeout_seconds = 20
    max_output_chars = 60000
    examples = [
        {"pattern": "class AgentRunner", "path": "backend/app", "literal": True},
        {"pattern": "TODO|FIXME", "include": ["*.py"], "case_sensitive": False},
    ]

    def resource(self, input_data: GrepSearchInput, workspace_root: Path) -> str:
        return str(resolve_workspace_path(workspace_root, input_data.path or "."))

    async def run(self, input_data: GrepSearchInput, ctx: ToolContext) -> ToolResult:
        workspace_root = ctx.workspace_root.resolve()
        root = resolve_workspace_path(workspace_root, input_data.path or ".")
        ensure_inside_workspace(workspace_root, root, action="search")
        if not root.exists():
            raise FileNotFoundError(f"Search path not found: {root}")
        flags = 0 if input_data.case_sensitive else re.IGNORECASE
        regex = re.compile(re.escape(input_data.pattern) if input_data.literal else input_data.pattern, flags)
        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        files = [path for path in files if self._include_file(path, workspace_root, input_data)]
        files = files[: input_data.max_files]

        matches: list[dict[str, object]] = []
        skipped_secret = 0
        for file in files:
            decision = evaluate_default_policy(
                permission_key="read.file",
                resource=str(file.resolve()),
                input_json={"path": str(file)},
                workspace_root=workspace_root,
            )
            if decision.action != PermissionAction.ALLOW:
                skipped_secret += 1
                continue
            data = file.read_bytes()
            if looks_binary(data[: min(len(data), 4096)]):
                continue
            lines = data.decode("utf-8", errors="replace").splitlines()
            for line_no, line in enumerate(lines, 1):
                match = regex.search(line)
                if not match:
                    continue
                before = lines[max(0, line_no - input_data.context_before - 1) : line_no - 1]
                after = lines[line_no : line_no + input_data.context_after]
                snippet = redact_text(line[:2000])
                matches.append(
                    {
                        "file": str(file),
                        "line": line_no,
                        "column": match.start() + 1,
                        "snippet": snippet,
                        "before": [redact_text(item[:2000]) for item in before],
                        "after": [redact_text(item[:2000]) for item in after],
                    }
                )
                if len(matches) >= input_data.max_matches:
                    break
            if len(matches) >= input_data.max_matches:
                break

        truncated = len(matches) >= input_data.max_matches or (root.is_dir() and len(files) >= input_data.max_files)
        return ToolResult(
            title=input_data.pattern,
            output={
                "matches": matches,
                "match_count": len(matches),
                "truncated": truncated,
                "searched_files": len(files),
                "skipped_protected_files": skipped_secret,
            },
            metadata={
                "matches": len(matches),
                "truncated": truncated,
                "searched_files": len(files),
                "skipped_protected_files": skipped_secret,
            },
            redacted=skipped_secret > 0,
            truncated=truncated,
        )

    def _include_file(self, path: Path, workspace_root: Path, input_data: GrepSearchInput) -> bool:
        rel = path.relative_to(workspace_root).as_posix()
        if input_data.include and not any(fnmatch.fnmatch(rel, pattern) for pattern in input_data.include):
            return False
        if input_data.exclude and any(fnmatch.fnmatch(rel, pattern) for pattern in input_data.exclude):
            return False
        return True
