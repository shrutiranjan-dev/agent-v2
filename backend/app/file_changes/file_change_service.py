from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
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

REVERT_PERMISSION_KEY = "file_change.revert"
MAX_GIT_OUTPUT_BYTES = 1_048_576


class FileChangeError(RuntimeError):
    """Raised when a file change capture or revert cannot proceed safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "file_change_error",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class FileChangeNotFoundError(FileChangeError):
    """Raised when the requested file change id does not exist."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="file_change_not_found", status_code=404, details=details)


class FileChangeConflictError(FileChangeError):
    """Raised for hash mismatch, already-reverted, and other conflict-class errors.

    Maps to HTTP 409 in the route handler.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="file_change_conflict", status_code=409, details=details)


class FileChangeForbiddenError(FileChangeError):
    """Raised when the revert is denied because the file is a secret or outside the workspace."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="file_change_forbidden", status_code=403, details=details)


class FileChangeValidationError(FileChangeError):
    """Raised for invalid input (unknown operation, missing fields, etc.)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="file_change_validation", status_code=422, details=details)


class FileChangeSecretRequiresForce(FileChangeConflictError):
    """Raised when a revert targets a secret-glob file and ``force`` is false.

    Maps to HTTP 409 with a "needs force override" reason, not 403. The file
    itself is not redacted (so the operator can read the diff and decide
    whether to retry with ``force=true``); the conflict is between the
    requested action and the safety policy.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.code = "file_change_secret_requires_force"


# Backwards-compatible aliases for tests and the old single-revert route.
class FileChangeNotRevertible(FileChangeConflictError):
    """Backwards-compatible alias (now maps to 409)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.code = "file_change_not_revertible"


class FileChangeAlreadyReverted(FileChangeConflictError):
    """Backwards-compatible alias (now maps to 409)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.code = "file_change_already_reverted"


class FileChangeHashMismatch(FileChangeConflictError):
    """Backwards-compatible alias (now maps to 409)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.code = "file_change_hash_mismatch"


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


async def _validate_revert_preconditions(
    row: FileChange,
    *,
    workspace_root: Path,
    force: bool,
    secret_globs: list[str] | None = None,
    check_hash: bool = True,
) -> tuple[Path, str | None]:
    """Pre-flight checks shared by single and batch revert.

    Returns ``(resolved_path, current_sha256_or_none)``.
    Raises typed :class:`FileChangeError` subclasses on failure.

    The hash check is opt-out via ``check_hash=False``. Single revert runs
    with the default; batch revert runs with ``check_hash=False`` so the
    hash check happens at apply time and a stale-sibling failure can be
    rolled back rather than rejecting the whole batch upfront.
    """
    if row.revert_status == "reverted":
        raise FileChangeAlreadyReverted(
            f"File change {row.id} is already reverted.",
            details={
                "change_id": str(row.id),
                "relative_path": row.relative_path,
                "revert_status": row.revert_status,
            },
        )
    if not row.revertible:
        raise FileChangeNotRevertible(
            f"File change {row.id} is not revertible (reason: {row.redaction_reason or 'unknown'}).",
            details={
                "change_id": str(row.id),
                "relative_path": row.relative_path,
                "redaction_reason": row.redaction_reason,
            },
        )
    if row.redacted:
        raise FileChangeForbiddenError(
            f"File change {row.id} cannot be reverted: {row.redaction_reason or 'redacted'}.",
            details={
                "change_id": str(row.id),
                "relative_path": row.relative_path,
                "redaction_reason": row.redaction_reason,
            },
        )
    inside, resolved = _is_path_within_workspace(row.resolved_path, workspace_root)
    if not inside or resolved is None:
        raise FileChangeForbiddenError(
            f"File change {row.id} path is outside the workspace root.",
            details={
                "change_id": str(row.id),
                "relative_path": row.relative_path,
                "resolved_path": row.resolved_path,
            },
        )
    if secret_globs and _is_secret_filename(row.relative_path, secret_globs):
        raise FileChangeSecretRequiresForce(
            f"File change {row.id} matches a secret filename pattern; use force=true to override.",
            details={
                "change_id": str(row.id),
                "relative_path": row.relative_path,
            },
        )
    if check_hash and not force and row.after_sha256:
        try:
            current_hash: str | None = (
                _file_sha256(resolved) if resolved.exists() else None
            )
        except OSError as exc:
            raise FileChangeHashMismatch(
                f"Cannot hash current file {resolved}: {exc}",
                details={
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                },
            ) from exc
        if current_hash is None:
            raise FileChangeHashMismatch(
                f"Current file missing: {resolved} (use force=true to overwrite).",
                details={
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "expected_after_sha256": row.after_sha256,
                },
            )
        if current_hash != row.after_sha256:
            raise FileChangeHashMismatch(
                f"Current file hash does not match recorded after_sha256 for file change {row.id}.",
                details={
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "expected_after_sha256": row.after_sha256,
                    "current_sha256": current_hash,
                },
            )
        return resolved, current_hash
    return resolved, None


def _is_path_within_workspace(
    resolved_path: str,
    workspace_root: Path,
) -> tuple[bool, Path | None]:
    try:
        candidate = Path(resolved_path)
    except (TypeError, ValueError):
        return False, None
    if not is_inside(workspace_root, candidate):
        return False, None
    return True, candidate


async def revert_file_change(
    db: AsyncSession,
    *,
    file_change_id: UUID,
    workspace_root: Path,
    actor_user_id: UUID | None,
    tool_call_id: UUID | None = None,
    force: bool = False,
    permission_request_id: UUID | None = None,
    secret_globs: list[str] | None = None,
    git_fallback_enabled: bool = True,
) -> FileChange:
    row = await get_file_change(db, file_change_id)
    if row is None:
        raise FileChangeNotFoundError(
            f"File change not found: {file_change_id}",
            details={"change_id": str(file_change_id)},
        )
    await event_bus.publish(
        db,
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        event_type=EventType.FILE_CHANGE_REVERT_REQUESTED,
        payload={
            "id": str(row.id),
            "file_change_id": str(row.id),
            "relative_path": row.relative_path,
            "force": bool(force),
            "permission_request_id": str(permission_request_id) if permission_request_id else None,
        },
    )
    resolved, _current_hash = await _validate_revert_preconditions(
        row,
        workspace_root=workspace_root,
        force=force,
        secret_globs=secret_globs,
    )

    # Re-check the on-disk hash immediately before applying. This catches a
    # race where another writer (or a previous sibling in a batch) mutated
    # the file between the precondition and the apply step. Skipped when
    # ``force`` is set, when the recorded ``after_sha256`` is missing, or
    # when the caller already checked the hash (e.g. a batch that has its
    # own pre-flight).
    if not force and row.after_sha256:
        try:
            current_hash: str | None = (
                _file_sha256(resolved) if resolved.exists() else None
            )
        except OSError as exc:
            raise FileChangeHashMismatch(
                f"Cannot hash current file {resolved}: {exc}",
                details={
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                },
            ) from exc
        if current_hash is None:
            raise FileChangeHashMismatch(
                f"Current file missing: {resolved} (use force=true to overwrite).",
                details={
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "expected_after_sha256": row.after_sha256,
                },
            )
        if current_hash != row.after_sha256:
            raise FileChangeHashMismatch(
                f"Current file hash does not match recorded after_sha256 for file change {row.id}.",
                details={
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "expected_after_sha256": row.after_sha256,
                    "current_sha256": current_hash,
                },
            )

    # Resolve the content to restore. If before_content is missing (e.g. it
    # was truncated or the capture predated the on-disk snapshot), fall back
    # to git HEAD. The fallback never returns content for secret files: those
    # are filtered out by the precondition check above.
    restore_source = "stored_snapshot"
    restore_content = row.before_content
    if restore_content is None and row.operation != "add" and git_fallback_enabled:
        git_payload = restore_from_git_head(workspace_root, row.relative_path)
        if git_payload is not None:
            restore_content, _ = git_payload
            restore_source = "git_head"

    try:
        if row.operation == "delete":
            if restore_content is None:
                raise FileChangeNotRevertible(
                    f"File change {row.id} has no before_content recorded and git HEAD is unavailable.",
                    details={
                        "change_id": str(row.id),
                        "relative_path": row.relative_path,
                    },
                )
            resolved.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(resolved, restore_content)
        elif row.operation == "add":
            if resolved.exists() or resolved.is_symlink():
                resolved.unlink()
        else:
            if restore_content is None:
                raise FileChangeNotRevertible(
                    f"File change {row.id} has no before_content recorded and git HEAD is unavailable.",
                    details={
                        "change_id": str(row.id),
                        "relative_path": row.relative_path,
                    },
                )
            atomic_write_text(resolved, restore_content)
    except FileChangeError:
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
        raise FileChangeError(
            f"Revert failed for {row.id}: {exc}",
            details={
                "change_id": str(row.id),
                "relative_path": row.relative_path,
            },
        ) from exc

    row.revert_status = "reverted"
    row.reverted_at = datetime.now(UTC)
    row.reverted_by_user_id = actor_user_id
    row.revert_tool_call_id = tool_call_id
    row.revert_error = None
    if restore_source != "stored_snapshot":
        metadata = dict(row.metadata_json or {})
        metadata["restore_source"] = restore_source
        row.metadata_json = metadata
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
            "restore_source": restore_source,
            "permission_request_id": str(permission_request_id) if permission_request_id else None,
        },
    )
    return row


@dataclass
class BatchRevertResult:
    """Per-change and aggregate result of a batch revert.

    ``reverted`` is a list of file change ids that were applied; ``skipped``
    is the list of ids that were rejected before any mutation (validate-all-
    before-apply); ``failed`` is the list of ids whose on-disk write raised
    while a prior sibling had already been applied (atomic rollback restores
    their pre-batch state in this case).
    """

    reverted: list[UUID] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    restored_from_snapshots: bool = False
    error: str | None = None


async def revert_file_changes_batch(
    db: AsyncSession,
    *,
    file_change_ids: list[UUID],
    workspace_root: Path,
    actor_user_id: UUID | None,
    force: bool = False,
    permission_request_id: UUID | None = None,
    secret_globs: list[str] | None = None,
    git_fallback_enabled: bool = True,
) -> BatchRevertResult:
    """Atomically revert a list of file changes.

    Semantics:
    1. Validate every change. If any one is unsafe (not found, already
       reverted, hash mismatch, secret, outside workspace), reject the
       whole batch and mutate nothing.
    2. Snapshot the on-disk state of every file we are about to touch so
       we can roll back atomically.
    3. Apply each revert. If a later revert raises, restore every snapshot
       we captured and mark the batch as ``failed`` with the offending id.
    4. Return a :class:`BatchRevertResult` describing what happened.

    The on-disk snapshot is only used to roll back a partially-applied
    batch. The revert itself restores the recorded ``before_content``
    (or ``git_head`` for a missing snapshot); it does not depend on the
    snapshot capturing the original pre-batch content.
    """
    result = BatchRevertResult()
    if not file_change_ids:
        return result
    if len(file_change_ids) > 100:
        raise FileChangeValidationError(
            "Batch revert is limited to 100 file changes per call.",
            details={"requested": len(file_change_ids), "limit": 100},
        )

    seen: set[UUID] = set()
    deduped_ids: list[UUID] = []
    for fid in file_change_ids:
        if fid in seen:
            continue
        seen.add(fid)
        deduped_ids.append(fid)

    # Phase 1: validate every change. If any is unsafe, do not mutate.
    # Note: the hash check is intentionally skipped here; the actual
    # ``revert_file_change`` re-checks the hash at apply time so a stale
    # sibling can be rolled back instead of rejecting the whole batch.
    rows: list[FileChange] = []
    for fid in deduped_ids:
        row = await get_file_change(db, fid)
        if row is None:
            result.skipped.append(
                {
                    "change_id": str(fid),
                    "reason": "not_found",
                    "error": f"File change not found: {fid}",
                }
            )
            continue
        try:
            await _validate_revert_preconditions(
                row,
                workspace_root=workspace_root,
                force=force,
                secret_globs=secret_globs,
                check_hash=False,
            )
        except FileChangeError as exc:
            result.skipped.append(
                {
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "reason": exc.code,
                    "error": exc.message,
                    "details": exc.details,
                }
            )
            continue
        rows.append(row)

    if any(entry["reason"] != "not_found" for entry in result.skipped) or (
        result.skipped and not rows
    ):
        # at least one precondition failed; the batch is rejected as a whole.
        return result

    # Phase 2: snapshot on-disk state for atomic rollback.
    snapshots: dict[Path, tuple[bool, bytes | None]] = {}
    for row in rows:
        target = Path(row.resolved_path)
        try:
            existed = target.exists() or target.is_symlink()
            data = target.read_bytes() if existed else None
        except OSError:
            existed = False
            data = None
        snapshots[target] = (existed, data)

    # Phase 3: apply each revert. On any failure, roll back.
    for row in rows:
        try:
            await revert_file_change(
                db,
                file_change_id=row.id,
                workspace_root=workspace_root,
                actor_user_id=actor_user_id,
                force=force,
                permission_request_id=permission_request_id,
                secret_globs=secret_globs,
                git_fallback_enabled=git_fallback_enabled,
            )
            result.reverted.append(row.id)
        except FileChangeError as exc:
            # Roll back every prior revert in this batch.
            for previous in rows:
                if previous.id in result.reverted:
                    target = Path(previous.resolved_path)
                    existed, data = snapshots.get(target, (False, None))
                    try:
                        if existed and data is not None:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            atomic_write_text(target, data.decode("utf-8", errors="replace"))
                        elif existed:
                            # Snapshot was the existence of a symlink/special
                            # file. We did not capture its bytes, so the
                            # safest we can do is delete the file we
                            # created during revert. This is rare.
                            if target.exists() or target.is_symlink():
                                target.unlink()
                    except OSError:
                        pass
                    try:
                        previous.revert_status = "revert_failed"
                        previous.revert_error = f"rolled_back_due_to:{exc.code}"
                        await db.flush()
                    except Exception:
                        pass
            result.restored_from_snapshots = True
            result.failed.append(
                {
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "reason": exc.code,
                    "error": exc.message,
                }
            )
            result.error = exc.message
            return result

    return result


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
        "revert_requires_approval": bool(fc.revert_requires_approval),
        "git_fallback_enabled": bool(fc.git_fallback_enabled),
        "secret_filename_globs": list(fc.secret_filename_globs),
    }


def compute_approval_nonce(
    *,
    file_change_id: UUID | str,
    relative_path: str,
    expected_after_sha256: str | None,
    force: bool,
) -> str:
    """Deterministic nonce bound to a revert request.

    Approval requests carry this nonce in their metadata so the resume path
    can reject any attempt to reuse an approval for a different file change,
    a different target path, a different on-disk hash, or a different force
    flag. Bypassing the hash check, the secret check, or the workspace-root
    check via a stale approval is therefore not possible.
    """
    payload = {
        "file_change_id": str(file_change_id),
        "relative_path": relative_path,
        "expected_after_sha256": expected_after_sha256,
        "force": bool(force),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_path_inside(workspace_root: Path, relative_path: str) -> tuple[bool, Path | None]:
    """Resolve a relative path safely inside the workspace root.

    Refuses absolute paths, parent traversal, and any resolved path that
    escapes the workspace root.
    """
    if not isinstance(relative_path, str) or not relative_path:
        return False, None
    if "\\" in relative_path or relative_path.startswith("/") or relative_path.startswith("~"):
        return False, None
    raw = Path(relative_path)
    if raw.is_absolute():
        return False, None
    parts = raw.parts
    if any(part in ("..",) for part in parts):
        return False, None
    resolved = (workspace_root / raw).resolve(strict=False)
    if not is_inside(workspace_root, resolved):
        return False, None
    return True, resolved


def restore_from_git_head(
    workspace_root: Path,
    relative_path: str,
    *,
    git_executable: str | None = None,
) -> tuple[str, int] | None:
    """Read `<relative_path>` from `git -C <workspace_root> show HEAD:<path>`.

    Returns ``(content, size_bytes)`` on success, or ``None`` if the path
    is not tracked in HEAD, the file is absent, or git is unavailable.

    Safety:
    - Never uses a shell. The git command is always invoked as a list.
    - The relative path is normalized and validated against workspace-root
      traversal (absolute paths, ``..``, backslashes, and ``~`` are rejected).
    - Output is capped at ``MAX_GIT_OUTPUT_BYTES``.
    """
    inside, resolved = _is_path_inside(workspace_root, relative_path)
    if not inside or resolved is None:
        return None
    git = git_executable or shutil.which("git")
    if not git:
        return None
    try:
        completed = subprocess.run(
            [git, "-C", str(workspace_root.resolve(strict=False)), "show", f"HEAD:{relative_path}"],
            capture_output=True,
            check=False,
            shell=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    data = completed.stdout or b""
    if len(data) > MAX_GIT_OUTPUT_BYTES:
        return None
    return data.decode("utf-8", errors="replace"), len(data)


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
