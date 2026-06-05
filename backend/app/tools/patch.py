import asyncio
import re
import tempfile
from pathlib import Path

from pydantic import BaseModel

from backend.app.core.redaction import redact_text
from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    ensure_inside_workspace,
    resolve_workspace_path,
)
from backend.app.tools.write import atomic_write_text


class PatchApplyInput(BaseModel):
    patch_text: str
    dry_run: bool = False


class PatchApplyTool(BaseTool):
    name = "patch.apply"
    title = "Apply Patch"
    description = "Apply a workspace patch. Supports unified diff and the internal Begin/End patch format."
    category = "filesystem"
    input_model = PatchApplyInput
    permission_key = "patch.apply"
    risk_level = "high"
    timeout_seconds = 20
    max_output_chars = 60000
    examples = [
        {"patch_text": "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old\n+new\n", "dry_run": True},
    ]

    def resource(self, input_data: PatchApplyInput, workspace_root: Path) -> str:
        paths = self._paths_from_patch(input_data.patch_text, workspace_root)
        return "\n".join(str(path) for path in paths) if paths else "*"

    async def run(self, input_data: PatchApplyInput, ctx: ToolContext) -> ToolResult:
        if "GIT binary patch" in input_data.patch_text or "\x00" in input_data.patch_text:
            return ToolResult.failure(
                code="binary_patch_refused",
                message="Binary patches are not supported.",
                recoverable=False,
            )
        text = input_data.patch_text.replace("\r\n", "\n").replace("\r", "\n")
        if text.startswith("*** Begin Patch"):
            return self._run_internal_patch(text, ctx, dry_run=input_data.dry_run)
        return await self._run_unified_diff(text, ctx, dry_run=input_data.dry_run)

    def _run_internal_patch(self, patch_text: str, ctx: ToolContext, *, dry_run: bool) -> ToolResult:
        lines = patch_text.splitlines()
        if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
            return ToolResult.failure(code="invalid_patch", message="Patch must start with *** Begin Patch and end with *** End Patch.")
        idx = 1
        changed: list[dict[str, object]] = []
        while idx < len(lines) - 1:
            line = lines[idx]
            if line.startswith("*** Add File: "):
                rel = line.removeprefix("*** Add File: ").strip()
                target = resolve_workspace_path(ctx.workspace_root, rel)
                ensure_inside_workspace(ctx.workspace_root, target, action="patch")
                idx += 1
                content: list[str] = []
                while idx < len(lines) - 1 and not lines[idx].startswith("*** "):
                    if not lines[idx].startswith("+"):
                        return ToolResult.failure(code="invalid_patch", message="Add file lines must start with '+'.")
                    content.append(lines[idx][1:])
                    idx += 1
                if target.exists():
                    return ToolResult.failure(code="file_exists", message=f"Cannot add existing file: {target}")
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_text(target, "\n".join(content) + ("\n" if content else ""))
                changed.append({"path": str(target), "type": "add", "additions": len(content), "deletions": 0})
                continue
            if line.startswith("*** Delete File: "):
                rel = line.removeprefix("*** Delete File: ").strip()
                target = resolve_workspace_path(ctx.workspace_root, rel)
                ensure_inside_workspace(ctx.workspace_root, target, action="patch")
                if not target.exists():
                    return ToolResult.failure(code="missing_file", message=f"Cannot delete missing file: {target}")
                deletions = len(target.read_text(encoding="utf-8", errors="replace").splitlines()) if target.is_file() else 0
                if not dry_run:
                    target.unlink()
                changed.append({"path": str(target), "type": "delete", "additions": 0, "deletions": deletions})
                idx += 1
                continue
            if line.startswith("*** Update File: "):
                rel = line.removeprefix("*** Update File: ").strip()
                target = resolve_workspace_path(ctx.workspace_root, rel)
                ensure_inside_workspace(ctx.workspace_root, target, action="patch")
                if not target.exists():
                    return ToolResult.failure(code="missing_file", message=f"Cannot update missing file: {target}")
                original = target.read_text(encoding="utf-8")
                idx += 1
                remove: list[str] = []
                add: list[str] = []
                while idx < len(lines) - 1 and not lines[idx].startswith("*** "):
                    current = lines[idx]
                    if current.startswith("@@"):
                        idx += 1
                        continue
                    if current.startswith("-"):
                        remove.append(current[1:])
                    elif current.startswith("+"):
                        add.append(current[1:])
                    elif current.startswith(" "):
                        pass
                    else:
                        return ToolResult.failure(code="invalid_patch", message=f"Invalid update line: {current}")
                    idx += 1
                old = "\n".join(remove)
                new = "\n".join(add)
                if not old or old not in original:
                    return ToolResult.failure(code="context_not_found", message=f"Patch context not found in {target}")
                if not dry_run:
                    atomic_write_text(target, original.replace(old, new, 1))
                changed.append({"path": str(target), "type": "update", "additions": len(add), "deletions": len(remove)})
                continue
            return ToolResult.failure(code="invalid_patch", message=f"Unsupported patch hunk: {line}")
        return self._result(changed, dry_run=dry_run)

    async def _run_unified_diff(self, patch_text: str, ctx: ToolContext, *, dry_run: bool) -> ToolResult:
        paths = self._paths_from_patch(patch_text, ctx.workspace_root)
        if not paths:
            return ToolResult.failure(code="invalid_patch", message="No changed files found in unified diff.")
        for path in paths:
            ensure_inside_workspace(ctx.workspace_root, path, action="patch")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(patch_text)
            patch_file = Path(handle.name)
        try:
            selected_strip: int | None = None
            last_output = ""
            for strip in (1, 0):
                cmd = ["patch", "--batch", "--forward", "--reject-file", "-", f"-p{strip}", "-i", str(patch_file)]
                if dry_run:
                    cmd.insert(1, "--dry-run")
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(ctx.workspace_root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
                last_output = stdout.decode("utf-8", errors="replace")
                if proc.returncode == 0:
                    selected_strip = strip
                    break
            if selected_strip is None:
                return ToolResult.failure(
                    code="patch_failed",
                    message="Patch command failed.",
                    detail=redact_text(last_output[-4000:]),
                    recoverable=True,
                )
            stats = self._stats_from_unified_diff(patch_text, ctx.workspace_root)
            return self._result(stats, dry_run=dry_run, extra={"strip": selected_strip, "patch_output": redact_text(last_output[-4000:])})
        finally:
            patch_file.unlink(missing_ok=True)

    def _paths_from_patch(self, patch_text: str, workspace_root: Path) -> list[Path]:
        paths: list[Path] = []
        for line in patch_text.splitlines():
            if line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: ")):
                rel = line.split(": ", 1)[1].strip()
                paths.append(resolve_workspace_path(workspace_root, rel))
            if line.startswith(("--- ", "+++ ")):
                raw = line[4:].strip().split("\t", 1)[0]
                if raw == "/dev/null":
                    continue
                if raw.startswith(("a/", "b/")):
                    raw = raw[2:]
                paths.append(resolve_workspace_path(workspace_root, raw))
        return list(dict.fromkeys(paths))

    def _stats_from_unified_diff(self, patch_text: str, workspace_root: Path) -> list[dict[str, object]]:
        stats: dict[str, dict[str, object]] = {}
        current: str | None = None
        for line in patch_text.splitlines():
            if line.startswith("+++ "):
                raw = line[4:].strip().split("\t", 1)[0]
                if raw == "/dev/null":
                    continue
                if raw.startswith("b/"):
                    raw = raw[2:]
                current = str(resolve_workspace_path(workspace_root, raw))
                stats.setdefault(current, {"path": current, "type": "update", "additions": 0, "deletions": 0})
            elif current and line.startswith("+") and not line.startswith("+++"):
                stats[current]["additions"] = int(stats[current]["additions"]) + 1
            elif current and line.startswith("-") and not line.startswith("---"):
                stats[current]["deletions"] = int(stats[current]["deletions"]) + 1
        return list(stats.values())

    def _result(self, changed: list[dict[str, object]], *, dry_run: bool, extra: dict[str, object] | None = None) -> ToolResult:
        output = {
            "changed_files": changed,
            "file_count": len(changed),
            "additions": sum(int(item.get("additions", 0)) for item in changed),
            "deletions": sum(int(item.get("deletions", 0)) for item in changed),
            "dry_run": dry_run,
            **(extra or {}),
        }
        return ToolResult(
            title=f"{'Validated' if dry_run else 'Applied'} patch for {len(changed)} file(s)",
            output=output,
            metadata=output,
            redacted=bool(extra and "patch_output" in extra and REDACTION_MARKER_RE.search(str(extra.get("patch_output")))),
        )


REDACTION_MARKER_RE = re.compile(r"\[REDACTED\]")
