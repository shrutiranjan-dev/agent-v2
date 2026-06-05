import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    content_sha256,
    ensure_inside_workspace,
    file_sha256,
    resolve_workspace_path,
)


class WriteFileInput(BaseModel):
    path: str
    content: str
    create_dirs: bool = False
    backup: bool = True
    expected_existing_hash: str | None = None


def atomic_write_text(path: Path, content: str) -> None:
    data = content.encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


class WriteFileTool(BaseTool):
    name = "write.file"
    title = "Write File"
    description = "Atomically write complete UTF-8 content to a workspace file."
    category = "filesystem"
    input_model = WriteFileInput
    permission_key = "write.file"
    risk_level = "medium"
    timeout_seconds = 15
    examples = [
        {"path": "notes.txt", "content": "hello\\n", "create_dirs": False},
        {"path": "src/example.py", "content": "print('ok')\\n", "expected_existing_hash": "<sha256>"},
    ]

    def resource(self, input_data: WriteFileInput, workspace_root: Path) -> str:
        return str(resolve_workspace_path(workspace_root, input_data.path))

    async def run(self, input_data: WriteFileInput, ctx: ToolContext) -> ToolResult:
        target = resolve_workspace_path(ctx.workspace_root, input_data.path)
        ensure_inside_workspace(ctx.workspace_root, target, action="write")
        existed = target.exists()
        if target.exists() and target.is_dir():
            raise IsADirectoryError(f"Cannot write file over directory: {target}")
        if not target.parent.exists():
            if not input_data.create_dirs:
                raise FileNotFoundError(f"Parent directory does not exist: {target.parent}")
            target.parent.mkdir(parents=True, exist_ok=True)
        before_hash = file_sha256(target) if existed else None
        if input_data.expected_existing_hash and before_hash != input_data.expected_existing_hash:
            return ToolResult.failure(
                code="stale_file_hash",
                message="Refusing to overwrite because expected_existing_hash does not match current file.",
                detail={"expected": input_data.expected_existing_hash, "actual": before_hash},
                recoverable=True,
                metadata={"path": input_data.path, "resolved_path": str(target)},
            )

        backup_path: str | None = None
        if existed and input_data.backup:
            suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
            backup = target.with_name(f"{target.name}.{suffix}.bak")
            backup.write_bytes(target.read_bytes())
            backup_path = str(backup)

        atomic_write_text(target, input_data.content)
        digest = content_sha256(input_data.content)
        return ToolResult(
            title=str(target),
            output={
                "path": input_data.path,
                "resolved_path": str(target),
                "bytes_written": len(input_data.content.encode("utf-8")),
                "sha256": digest,
                "backup_path": backup_path,
                "created": not existed,
                "overwritten": existed,
            },
            metadata={
                "path": input_data.path,
                "resolved_path": str(target),
                "bytes_written": len(input_data.content.encode("utf-8")),
                "sha256": digest,
                "backup_path": backup_path,
                "created": not existed,
                "overwritten": existed,
                "previous_sha256": before_hash,
            },
        )
