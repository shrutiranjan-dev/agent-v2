from __future__ import annotations

import difflib
import fnmatch
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.core.redaction import redact_text
from backend.app.db.models import FileChange
from backend.app.runtime.event_bus import event_bus
from backend.app.tools.base import (
    is_inside,
    resolve_workspace_path,
)
from backend.app.tools.write import atomic_write_text

FILE_CHANGE_TOOLS = {"write.file", "edit.file", "patch.apply"}
OPERATION_BY_TOOL = {
    "write.file": "write",
    "edit.file": "edit",
    "patch.apply": "patch",
}


class FileChangeError(RuntimeError):
    """Raised when a file change capture or revert cannot proceed safely."""


class FileChangeNotRevertible(FileChangeError):
    """Raised when a change cannot be reverted (secret, missing before_content, etc.)."""


class FileChangeAlreadyReverted(FileChangeError):
    """Raised when attempting to revert a change that was already reverted."""


class FileChangeHashMismatch(FileChangeError):
    """Raised when the current file hash does not match the expected hash."""


@dataclass
class FileChangeCapture:
    tool_name: str
    operation: str
    relative_path: str
    resolved_path: str
    before_sha256: str | None
    after_sha256: str | None
    before_size_bytes: int | None
    after_size_bytes: int | None
    before_content: str | None
    after_content: str | None
    diff: str | None
    additions: int
    deletions: int
    replacement_count: int
    backup_path: str | None
    metadata: dict[str, Any]


@dataclass
class FileChangeContext:
    organization_id: UUID
    project_id: UUID
    workspace_id: UUID
    session_id: UUID
    agent_run_id: UUID | None
    tool_call_id: UUID | None
    workspace_root: Path


def _to_relative_path(resolved: Path, workspace_root: Path) -> str:
    try:
        return resolved.relative_to(workspace_root).as_posix()
    except ValueError:
        return resolved.name


def _is_secret_filename(relative_path: str, secret_globs: list[str]) -> bool:
    name = Path(relative_path).name.lower()
    for pattern in secret_globs:
        if fnmatch.fnmatch(name, pattern.lower()):
            return True
    return False


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truncate(value: str | None, *, limit: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if limit <= 0 or len(value) <= limit:
        return value, False
    return value[:limit] + "\n...truncated...", True


def _relative_path_within_workspace(resolved: Path, workspace_root: Path) -> str | None:
    if not is_inside(workspace_root, resolved):
        return None
    return _to_relative_path(resolved, workspace_root)


def _build_capture_for_write(
    *,
    input_json: dict[str, Any],
    result_metadata: dict[str, Any],
    workspace_root: Path,
) -> FileChangeCapture | None:
    relative_input = input_json.get("path")
    if not isinstance(relative_input, str) or not relative_input:
        return None
    target = resolve_workspace_path(workspace_root, relative_input)
    relative_path = _relative_path_within_workspace(target, workspace_root)
    if relative_path is None:
        return None
    content = str(input_json.get("content", ""))
    previous_sha = result_metadata.get("previous_sha256")
    after_sha = result_metadata.get("sha256") or _content_sha256(content)
    before_content_raw = result_metadata.get("before_content")
    if isinstance(before_content_raw, str):
        before_content = before_content_raw
    else:
        before_content = None
    additions = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    deletions = 0
    if before_content is not None:
        deletions = before_content.count("\n") + (1 if before_content and not before_content.endswith("\n") else 0)
    elif previous_sha:
        try:
            before_content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
        except OSError:
            before_content = None
        if before_content is not None:
            deletions = before_content.count("\n") + (1 if before_content and not before_content.endswith("\n") else 0)
    is_create = bool(result_metadata.get("created")) and not before_content
    operation = "add" if is_create else "write"
    diff = "".join(
        difflib.unified_diff(
            (before_content or "").splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=relative_path,
            tofile=relative_path,
        )
    )
    return FileChangeCapture(
        tool_name="write.file",
        operation=operation,
        relative_path=relative_path,
        resolved_path=str(target),
        before_sha256=previous_sha,
        after_sha256=after_sha,
        before_size_bytes=len(before_content.encode("utf-8")) if before_content is not None else None,
        after_size_bytes=len(content.encode("utf-8")),
        before_content=before_content,
        after_content=content,
        diff=diff or None,
        additions=additions,
        deletions=deletions,
        replacement_count=1,
        backup_path=result_metadata.get("backup_path"),
        metadata={"created": is_create},
    )


def _build_capture_for_edit(
    *,
    input_json: dict[str, Any],
    result_metadata: dict[str, Any],
    workspace_root: Path,
) -> FileChangeCapture | None:
    if result_metadata.get("dry_run"):
        return None
    relative_input = input_json.get("path")
    if not isinstance(relative_input, str) or not relative_input:
        return None
    target = resolve_workspace_path(workspace_root, relative_input)
    relative_path = _relative_path_within_workspace(target, workspace_root)
    if relative_path is None:
        return None
    before_sha = result_metadata.get("before_sha256")
    after_sha = result_metadata.get("after_sha256")
    if not before_sha and not after_sha:
        return None
    diff = result_metadata.get("diff") if isinstance(result_metadata.get("diff"), str) else None
    if not diff:
        return None
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    before_content_raw = result_metadata.get("before_content")
    if isinstance(before_content_raw, str):
        before_content = before_content_raw
    else:
        before_content = None
    after_content_raw = result_metadata.get("after_content")
    if isinstance(after_content_raw, str):
        after_content = after_content_raw
    else:
        after_content = None
    if before_content is None and before_sha:
        try:
            before_content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
        except OSError:
            before_content = None
    if after_content is None and after_sha:
        try:
            after_content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
        except OSError:
            after_content = None
    return FileChangeCapture(
        tool_name="edit.file",
        operation="edit",
        relative_path=relative_path,
        resolved_path=str(target),
        before_sha256=before_sha,
        after_sha256=after_sha,
        before_size_bytes=result_metadata.get("before_size_bytes"),
        after_size_bytes=result_metadata.get("after_size_bytes"),
        before_content=before_content,
        after_content=after_content,
        diff=diff,
        additions=additions,
        deletions=deletions,
        replacement_count=int(result_metadata.get("replacements", 0) or 0),
        backup_path=None,
        metadata={},
    )


def _build_captures_for_patch(
    *,
    input_json: dict[str, Any],
    result_metadata: dict[str, Any],
    result_output: dict[str, Any],
    workspace_root: Path,
) -> list[FileChangeCapture]:
    if result_metadata.get("dry_run"):
        return []
    patch_text = input_json.get("patch_text")
    if not isinstance(patch_text, str):
        return []
    changed = list(result_output.get("changed_files") or result_metadata.get("changed_files") or [])
    if not changed:
        return []
    captures: list[FileChangeCapture] = []
    for entry in changed:
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        target = Path(raw_path)
        if not target.is_absolute():
            target = resolve_workspace_path(workspace_root, raw_path)
        relative_path = _relative_path_within_workspace(target, workspace_root)
        if relative_path is None:
            continue
        op = str(entry.get("type") or "update")
        additions = int(entry.get("additions", 0) or 0)
        deletions = int(entry.get("deletions", 0) or 0)
        before_content: str | None = None
        after_content: str | None = None
        if op == "delete":
            try:
                if target.exists() and target.is_file():
                    before_content = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before_content = None
        elif op == "add":
            try:
                if target.exists() and target.is_file():
                    after_content = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                after_content = None
        else:
            try:
                if target.exists() and target.is_file():
                    after_content = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                after_content = None
        before_sha = _content_sha256(before_content) if before_content is not None else None
        after_sha = _content_sha256(after_content) if after_content is not None else None
        diff = "".join(
            difflib.unified_diff(
                (before_content or "").splitlines(keepends=True),
                (after_content or "").splitlines(keepends=True),
                fromfile=relative_path,
                tofile=relative_path,
            )
        ) or None
        captures.append(
            FileChangeCapture(
                tool_name="patch.apply",
                operation=op if op in {"add", "update", "delete"} else "patch",
                relative_path=relative_path,
                resolved_path=str(target),
                before_sha256=before_sha,
                after_sha256=after_sha,
                before_size_bytes=len(before_content.encode("utf-8")) if before_content is not None else None,
                after_size_bytes=len(after_content.encode("utf-8")) if after_content is not None else None,
                before_content=before_content,
                after_content=after_content,
                diff=diff,
                additions=additions,
                deletions=deletions,
                replacement_count=1,
                backup_path=None,
                metadata={},
            )
        )
    return captures


def build_captures_for_tool(
    *,
    tool_name: str,
    input_json: dict[str, Any],
    result_output: dict[str, Any],
    result_metadata: dict[str, Any],
    workspace_root: Path,
) -> list[FileChangeCapture]:
    if tool_name not in FILE_CHANGE_TOOLS:
        return []
    if tool_name == "write.file":
        capture = _build_capture_for_write(
            input_json=input_json,
            result_metadata=result_metadata,
            workspace_root=workspace_root,
        )
        return [capture] if capture is not None else []
    if tool_name == "edit.file":
        capture = _build_capture_for_edit(
            input_json=input_json,
            result_metadata=result_metadata,
            workspace_root=workspace_root,
        )
        return [capture] if capture is not None else []
    if tool_name == "patch.apply":
        return _build_captures_for_patch(
            input_json=input_json,
            result_metadata=result_metadata,
            result_output=result_output,
            workspace_root=workspace_root,
        )
    return []


def _persist_capture(
    db: AsyncSession,
    *,
    ctx: FileChangeContext,
    capture: FileChangeCapture,
    settings_snapshot: dict[str, Any],
) -> FileChange:
    secret_globs = list(settings_snapshot.get("secret_filename_globs") or [])
    max_content = int(settings_snapshot.get("max_content_bytes") or 0)
    max_diff = int(settings_snapshot.get("max_diff_bytes") or 0)
    capture_content = bool(settings_snapshot.get("capture_content", True))
    capture_diff = bool(settings_snapshot.get("capture_diff", True))

    is_secret = _is_secret_filename(capture.relative_path, secret_globs)
    redacted = is_secret

    before_content = capture.before_content
    after_content = capture.after_content
    diff = capture.diff
    before_truncated = False
    after_truncated = False
    diff_truncated = False

    if not capture_content:
        before_content = None
        after_content = None
    if not capture_diff:
        diff = None

    if is_secret:
        before_content = None
        after_content = None
        diff = None
    else:
        if before_content is not None and max_content > 0:
            before_content, before_truncated = _truncate(before_content, limit=max_content)
        if after_content is not None and max_content > 0:
            after_content, after_truncated = _truncate(after_content, limit=max_content)
        if diff is not None and max_diff > 0:
            diff, diff_truncated = _truncate(diff, limit=max_diff)

    if before_content is not None:
        before_content = redact_text(before_content)
    if after_content is not None:
        after_content = redact_text(after_content)
    if diff is not None:
        diff = redact_text(diff)

    revertible = not is_secret and (capture.before_content is not None or capture.after_content is None)
    if capture.operation == "delete":
        revertible = not is_secret and capture.before_content is not None
    if capture.operation == "add":
        revertible = not is_secret and capture.after_content is not None

    row = FileChange(
        id=uuid4(),
        organization_id=ctx.organization_id,
        project_id=ctx.project_id,
        workspace_id=ctx.workspace_id,
        session_id=ctx.session_id,
        agent_run_id=ctx.agent_run_id,
        tool_call_id=ctx.tool_call_id,
        tool_name=capture.tool_name,
        operation=capture.operation,
        relative_path=capture.relative_path,
        resolved_path=capture.resolved_path,
        before_sha256=capture.before_sha256,
        after_sha256=capture.after_sha256,
        before_size_bytes=capture.before_size_bytes,
        after_size_bytes=capture.after_size_bytes,
        before_content=before_content,
        after_content=after_content,
        before_content_truncated=before_truncated,
        after_content_truncated=after_truncated,
        diff=diff,
        diff_truncated=diff_truncated,
        additions=capture.additions,
        deletions=capture.deletions,
        replacement_count=capture.replacement_count,
        backup_path=capture.backup_path,
        redacted=redacted,
        redaction_reason="secret_filename_match" if is_secret else None,
        revertible=revertible,
        revert_status="not_reverted",
        metadata_json=capture.metadata or {},
    )
    db.add(row)
    return row


async def capture_for_tool_call(
    db: AsyncSession,
    *,
    ctx: FileChangeContext,
    tool_name: str,
    input_json: dict[str, Any],
    result_output: dict[str, Any],
    result_metadata: dict[str, Any],
    settings_snapshot: dict[str, Any],
) -> list[FileChange]:
    captures = build_captures_for_tool(
        tool_name=tool_name,
        input_json=input_json,
        result_output=result_output,
        result_metadata=result_metadata,
        workspace_root=ctx.workspace_root,
    )
    rows: list[FileChange] = []
    for capture in captures:
        row = _persist_capture(
            db,
            ctx=ctx,
            capture=capture,
            settings_snapshot=settings_snapshot,
        )
        rows.append(row)
    if rows:
        await db.flush()
        for row in rows:
            await event_bus.publish(
                db,
                organization_id=row.organization_id,
                project_id=row.project_id,
                workspace_id=row.workspace_id,
                session_id=row.session_id,
                agent_run_id=row.agent_run_id,
                tool_call_id=row.tool_call_id,
                event_type=EventType.FILE_CHANGE_CREATED,
                payload={
                    "id": str(row.id),
                    "file_change_id": str(row.id),
                    "tool_name": row.tool_name,
                    "operation": row.operation,
                    "relative_path": row.relative_path,
                    "revertible": row.revertible,
                    "redacted": row.redacted,
                    "revert_status": row.revert_status,
                },
            )
    return rows


async def list_file_changes(
    db: AsyncSession,
    *,
    session_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    tool_call_id: UUID | None = None,
    relative_path: str | None = None,
    revert_status: str | None = None,
    limit: int = 200,
) -> list[FileChange]:
    if hasattr(db, "objects"):
        rows = [row for (model, _), row in db.objects.items() if model is FileChange]
        if session_id is not None:
            rows = [row for row in rows if row.session_id == session_id]
        if agent_run_id is not None:
            rows = [row for row in rows if row.agent_run_id == agent_run_id]
        if tool_call_id is not None:
            rows = [row for row in rows if row.tool_call_id == tool_call_id]
        if relative_path is not None:
            rows = [row for row in rows if row.relative_path == relative_path]
        if revert_status is not None:
            rows = [row for row in rows if row.revert_status == revert_status]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)[:limit]

    stmt: Select[tuple[FileChange]] = select(FileChange).order_by(FileChange.created_at.desc()).limit(limit)
    if session_id is not None:
        stmt = stmt.where(FileChange.session_id == session_id)
    if agent_run_id is not None:
        stmt = stmt.where(FileChange.agent_run_id == agent_run_id)
    if tool_call_id is not None:
        stmt = stmt.where(FileChange.tool_call_id == tool_call_id)
    if relative_path is not None:
        stmt = stmt.where(FileChange.relative_path == relative_path)
    if revert_status is not None:
        stmt = stmt.where(FileChange.revert_status == revert_status)
    result = await db.scalars(stmt)
    return list(result.all())


async def get_file_change(db: AsyncSession, file_change_id: UUID) -> FileChange | None:
    if hasattr(db, "objects"):
        return db.objects.get((FileChange, file_change_id))
    return await db.get(FileChange, file_change_id)


async def revert_file_change(
    db: AsyncSession,
    *,
    file_change_id: UUID,
    workspace_root: Path,
    actor_user_id: UUID | None,
    tool_call_id: UUID | None = None,
    force: bool = False,
) -> FileChange:
    row = await get_file_change(db, file_change_id)
    if row is None:
        raise FileChangeError(f"File change not found: {file_change_id}")
    if row.revert_status == "reverted":
        raise FileChangeAlreadyReverted(f"File change {file_change_id} is already reverted.")
    if not row.revertible:
        raise FileChangeNotRevertible(
            f"File change {file_change_id} is not revertible (reason: {row.redaction_reason or 'unknown'})."
        )
    if row.redacted:
        raise FileChangeNotRevertible(
            f"File change {file_change_id} cannot be reverted: {row.redaction_reason or 'redacted'}."
        )
    resolved = Path(row.resolved_path)
    if not is_inside(workspace_root, resolved):
        raise FileChangeNotRevertible(
            f"File change {file_change_id} path is outside the workspace root."
        )

    if not force and row.after_sha256:
        try:
            current_hash = _file_sha256(resolved) if resolved.exists() else None
        except OSError as exc:
            raise FileChangeHashMismatch(f"Cannot hash current file {resolved}: {exc}") from exc
        if current_hash is None:
            raise FileChangeHashMismatch(
                f"Current file missing: {resolved} (use force=true to overwrite)."
            )
        if current_hash != row.after_sha256:
            raise FileChangeHashMismatch(
                f"Current file hash does not match recorded after_sha256 for file change {file_change_id}."
            )

    try:
        if row.operation == "delete":
            if row.before_content is None:
                raise FileChangeNotRevertible(
                    f"File change {file_change_id} has no before_content recorded; cannot restore deleted file."
                )
            resolved.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(resolved, row.before_content)
        elif row.operation == "add":
            if resolved.exists() or resolved.is_symlink():
                resolved.unlink()
        else:
            if row.before_content is None:
                raise FileChangeNotRevertible(
                    f"File change {file_change_id} has no before_content recorded; cannot restore."
                )
            atomic_write_text(resolved, row.before_content)
    except FileChangeNotRevertible:
        raise
    except Exception as exc:
        row.revert_status = "revert_failed"
        row.revert_error = redact_text(str(exc))
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=row.organization_id,
            project_id=row.project_id,
            workspace_id=row.workspace_id,
            session_id=row.session_id,
            agent_run_id=row.agent_run_id,
            tool_call_id=row.tool_call_id,
            event_type=EventType.FILE_CHANGE_REVERT_FAILED,
            severity="error",
            payload={
                "id": str(row.id),
                "file_change_id": str(row.id),
                "relative_path": row.relative_path,
                "error": row.revert_error,
            },
        )
        raise FileChangeError(f"Revert failed for {file_change_id}: {exc}") from exc

    row.revert_status = "reverted"
    row.reverted_at = datetime.now(UTC)
    row.reverted_by_user_id = actor_user_id
    row.revert_tool_call_id = tool_call_id
    row.revert_error = None
    await db.flush()
    await event_bus.publish(
        db,
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        event_type=EventType.FILE_CHANGE_REVERTED,
        payload={
            "id": str(row.id),
            "file_change_id": str(row.id),
            "tool_name": row.tool_name,
            "operation": row.operation,
            "relative_path": row.relative_path,
            "tool_call_id": str(tool_call_id) if tool_call_id else None,
            "forced": bool(force),
        },
    )
    return row


def serialize_file_change(row: FileChange, *, include_content: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(row.id),
        "session_id": str(row.session_id),
        "agent_run_id": str(row.agent_run_id) if row.agent_run_id else None,
        "tool_call_id": str(row.tool_call_id) if row.tool_call_id else None,
        "tool_name": row.tool_name,
        "operation": row.operation,
        "relative_path": row.relative_path,
        "before_sha256": row.before_sha256,
        "after_sha256": row.after_sha256,
        "before_size_bytes": row.before_size_bytes,
        "after_size_bytes": row.after_size_bytes,
        "additions": row.additions,
        "deletions": row.deletions,
        "replacement_count": row.replacement_count,
        "backup_path": row.backup_path,
        "redacted": row.redacted,
        "redaction_reason": row.redaction_reason,
        "revertible": row.revertible,
        "revert_status": row.revert_status,
        "reverted_at": row.reverted_at.isoformat() if row.reverted_at else None,
        "reverted_by_user_id": str(row.reverted_by_user_id) if row.reverted_by_user_id else None,
        "revert_tool_call_id": str(row.revert_tool_call_id) if row.revert_tool_call_id else None,
        "revert_error": row.revert_error,
        "metadata": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_content:
        payload["diff"] = row.diff
        payload["diff_truncated"] = row.diff_truncated
        payload["before_content"] = row.before_content
        payload["after_content"] = row.after_content
        payload["before_content_truncated"] = row.before_content_truncated
        payload["after_content_truncated"] = row.after_content_truncated
    else:
        payload["diff"] = None
        payload["before_content"] = None
        payload["after_content"] = None
    return payload


def file_change_settings_snapshot() -> dict[str, Any]:
    from backend.app.core.config import get_settings

    settings = get_settings()
    fc = settings.file_changes
    return {
        "enabled": bool(fc.enabled),
        "capture_content": bool(fc.capture_content),
        "capture_diff": bool(fc.capture_diff),
        "max_content_bytes": int(fc.max_content_bytes),
        "max_diff_bytes": int(fc.max_diff_bytes),
        "secret_filename_globs": list(fc.secret_filename_globs),
    }


async def capture_from_tool_call(
    db: AsyncSession,
    *,
    ctx: FileChangeContext,
    tool_name: str,
    input_json: dict[str, Any],
    result_output: dict[str, Any],
    result_metadata: dict[str, Any],
) -> list[FileChange]:
    snapshot = file_change_settings_snapshot()
    if not snapshot["enabled"]:
        return []
    if tool_name not in FILE_CHANGE_TOOLS:
        return []
    return await capture_for_tool_call(
        db,
        ctx=ctx,
        tool_name=tool_name,
        input_json=input_json,
        result_output=result_output,
        result_metadata=result_metadata,
        settings_snapshot=snapshot,
    )
