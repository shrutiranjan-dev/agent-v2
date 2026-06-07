from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.db.models import Organization, Project, Session, Workspace
from backend.app.db.postgres import get_session
from backend.app.file_changes.file_change_service import (
    FILE_CHANGE_TOOLS,
    REVERT_PERMISSION_KEY,
    FileChangeConflictError,
    FileChangeContext,
    FileChangeError,
    FileChangeForbiddenError,
    FileChangeValidationError,
    capture_for_tool_call,
    compute_approval_nonce,
    get_file_change,
    list_file_changes,
    revert_file_change,
    revert_file_changes_batch,
    serialize_file_change,
)
from backend.app.permissions.service import permission_service
from backend.app.runtime.event_bus import event_bus
from backend.app.tools.base import is_inside, resolve_workspace_path
from backend.app.tools.write import atomic_write_text

router = APIRouter(prefix="/file-changes", tags=["file-changes"])


class RevertRequest(BaseModel):
    force: bool = False
    permission_request_id: UUID | None = None


class BatchRevertRequest(BaseModel):
    change_ids: list[UUID] = Field(..., min_length=1)
    force: bool = False
    permission_request_id: UUID | None = None


class _TestWriteRequest(BaseModel):
    path: str
    content: str
    before_content: str | None = None
    before_sha256: str | None = None
    tool_name: str = "write.file"
    operation: str = "write"
    organization_id: UUID | None = None
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    session_id: UUID | None = None


def _safe_relative_path(resolved_path: str, workspace_root: Path) -> str | None:
    try:
        resolved = Path(resolved_path)
    except (TypeError, ValueError):
        return None
    if not is_inside(workspace_root, resolved):
        return None
    try:
        return resolved.relative_to(workspace_root).as_posix()
    except ValueError:
        return None


def _file_change_error_response(exc: FileChangeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.code,
            "message": exc.message,
            "reason": exc.code,
            "details": exc.details,
        },
    )


def _revert_request_payload(
    row,
    *,
    force: bool,
) -> dict[str, Any]:
    nonce = compute_approval_nonce(
        file_change_id=row.id,
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=force,
    )
    return {
        "tool": "file_change.revert",
        "reason": "file_change_revert_requires_approval",
        "tool_name": "file_change.revert",
        "risk_level": "medium",
        "operation_type": "revert",
        "target_paths": [row.relative_path],
        "input_hash": nonce,
        "force": bool(force),
    }


async def _create_revert_permission_request(
    db: AsyncSession,
    *,
    row,
    force: bool,
) -> tuple[Any, str]:
    payload = _revert_request_payload(row, force=force)
    nonce = payload["input_hash"]
    from backend.app.permissions.models import PermissionRequestCreate

    request = await permission_service.create_request(
        db,
        PermissionRequestCreate(
            organization_id=row.organization_id,
            project_id=row.project_id,
            workspace_id=row.workspace_id,
            session_id=row.session_id,
            agent_run_id=row.agent_run_id,
            tool_call_id=row.tool_call_id,
            permission_key=REVERT_PERMISSION_KEY,
            resource=row.relative_path,
            input_json={
                "file_change_id": str(row.id),
                "relative_path": row.relative_path,
                "force": bool(force),
                "expected_after_sha256": row.after_sha256,
            },
            metadata_json=payload,
            requested_by_user_id=None,
        ),
    )
    await event_bus.publish(
        db,
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        event_type=EventType.FILE_CHANGE_REVERT_WAITING_PERMISSION,
        payload={
            "file_change_id": str(row.id),
            "permission_request_id": str(request.id),
            "relative_path": row.relative_path,
            "force": bool(force),
            "approval_nonce": nonce,
        },
    )
    return request, nonce


async def _verify_revert_approval(
    db: AsyncSession,
    *,
    row,
    permission_request_id: UUID,
    force: bool,
) -> None:
    from backend.app.db.models import PermissionRequest

    request = await db.get(PermissionRequest, permission_request_id)
    if request is None:
        raise FileChangeValidationError(
            f"Permission request {permission_request_id} not found.",
            details={"permission_request_id": str(permission_request_id)},
        )
    if request.permission_key != REVERT_PERMISSION_KEY:
        raise FileChangeForbiddenError(
            f"Permission request {permission_request_id} is not a file_change.revert request.",
            details={
                "permission_request_id": str(permission_request_id),
                "permission_key": request.permission_key,
            },
        )
    if str(request.status) != "approved":
        raise FileChangeConflictError(
            f"Permission request {permission_request_id} is not approved (status={request.status}).",
            details={
                "permission_request_id": str(permission_request_id),
                "status": str(request.status),
            },
        )
    expected_nonce = compute_approval_nonce(
        file_change_id=row.id,
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=force,
    )
    stored_nonce = str((request.metadata_json or {}).get("input_hash") or "")
    if not stored_nonce or stored_nonce != expected_nonce:
        raise FileChangeForbiddenError(
            "Permission request does not match this revert request "
            "(change_id/relative_path/expected_after_sha256/force mismatch).",
            details={
                "permission_request_id": str(permission_request_id),
                "change_id": str(row.id),
            },
        )


@router.get("")
async def list_file_changes_route(
    session_id: UUID | None = None,
    run_id: UUID | None = Query(default=None, alias="run_id"),
    tool_call_id: UUID | None = None,
    path: str | None = None,
    revert_status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await list_file_changes(
        db,
        session_id=session_id,
        agent_run_id=run_id,
        tool_call_id=tool_call_id,
        relative_path=path,
        revert_status=revert_status,
        limit=limit,
    )
    return {
        "file_changes": [serialize_file_change(row, include_content=False) for row in rows],
        "count": len(rows),
    }


@router.get("/{file_change_id}")
async def get_file_change_route(
    file_change_id: UUID,
    include_content: bool = True,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await get_file_change(db, file_change_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "file_change_not_found", "message": f"File change not found: {file_change_id}"},
        )
    return {"file_change": serialize_file_change(row, include_content=include_content)}


async def _revert_one(
    db: AsyncSession,
    *,
    file_change_id: UUID,
    force: bool,
    permission_request_id: UUID | None,
    secret_globs: list[str] | None,
    git_fallback_enabled: bool,
) -> Any:
    return await revert_file_change(
        db,
        file_change_id=file_change_id,
        workspace_root=get_settings().runtime.workspace_root,
        actor_user_id=None,
        force=force,
        permission_request_id=permission_request_id,
        secret_globs=secret_globs,
        git_fallback_enabled=git_fallback_enabled,
    )


async def _prepare_revert(
    db: AsyncSession,
    *,
    file_change_id: UUID,
    force: bool,
    permission_request_id: UUID | None,
) -> tuple[Any, dict[str, Any], list[str], bool]:
    """Common pre-flight for single and batch revert: load row, run approval gate.

    Returns ``(row, settings_snapshot, secret_globs, git_fallback_enabled)``.
    Raises HTTPException with the right status code on the gating path.

    Order is important: redaction / not-revertible / outside-workspace checks
    must fire before the approval gate, so a 403 is never silently converted
    into a 202 ``waiting_permission`` response for a change the operator
    cannot legally revert.
    """
    settings = get_settings()
    fc = settings.file_changes
    secret_globs = list(fc.secret_filename_globs)
    git_fallback_enabled = bool(fc.git_fallback_enabled)

    row = await get_file_change(db, file_change_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "file_change_not_found",
                "message": f"File change not found: {file_change_id}",
            },
        )

    if row.revert_status == "reverted":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "file_change_already_reverted",
                "message": f"File change {file_change_id} is already reverted.",
                "reason": "file_change_already_reverted",
                "details": {"change_id": str(row.id), "relative_path": row.relative_path},
            },
        )
    if row.redacted or not row.revertible:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "file_change_forbidden",
                "message": f"Revert denied: {row.redaction_reason or 'redacted or not revertible'}.",
                "reason": "file_change_forbidden",
                "details": {
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "redacted": bool(row.redacted),
                    "revertible": bool(row.revertible),
                },
            },
        )
    if not is_inside(settings.runtime.workspace_root, Path(row.resolved_path)):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "file_change_forbidden",
                "message": f"File change {file_change_id} path is outside the workspace root.",
                "reason": "file_change_forbidden",
                "details": {
                    "change_id": str(row.id),
                    "relative_path": row.relative_path,
                    "resolved_path": row.resolved_path,
                },
            },
        )
    if not force and _is_path_secret(row.relative_path, secret_globs):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "file_change_secret_requires_force",
                "message": "Revert denied: file matches a secret filename pattern; use force=true to override.",
                "reason": "file_change_secret_requires_force",
                "details": {"change_id": str(row.id), "relative_path": row.relative_path},
            },
        )

    requires_approval = bool(fc.revert_requires_approval)
    if requires_approval and permission_request_id is None:
        request, nonce = await _create_revert_permission_request(db, row=row, force=force)
        await db.commit()
        raise HTTPException(
            status_code=202,
            detail={
                "error": "permission_pending",
                "code": "permission_pending",
                "message": (
                    "Revert is permissioned. Approve the permission request and retry "
                    "with the permission_request_id to execute the revert."
                ),
                "status": "waiting_permission",
                "permission_request_id": str(request.id),
                "approval_nonce": nonce,
                "change_id": str(row.id),
            },
        )
    if requires_approval and permission_request_id is not None:
        try:
            await _verify_revert_approval(
                db,
                row=row,
                permission_request_id=permission_request_id,
                force=force,
            )
        except FileChangeError as exc:
            await db.rollback()
            raise _file_change_error_response(exc) from exc
        await event_bus.publish(
            db,
            organization_id=row.organization_id,
            project_id=row.project_id,
            workspace_id=row.workspace_id,
            session_id=row.session_id,
            agent_run_id=row.agent_run_id,
            tool_call_id=row.tool_call_id,
            event_type=EventType.FILE_CHANGE_REVERT_APPROVED,
            payload={
                "file_change_id": str(row.id),
                "permission_request_id": str(permission_request_id),
            },
        )

    return row, {"force": force, "settings": settings}, secret_globs, git_fallback_enabled


def _is_path_secret(relative_path: str, secret_globs: list[str]) -> bool:
    import fnmatch as _fn

    name = Path(relative_path).name.lower()
    for pattern in secret_globs:
        if _fn.fnmatch(name, pattern.lower()):
            return True
    return False


@router.post("/{file_change_id}/revert")
async def revert_file_change_route(
    file_change_id: UUID,
    payload: RevertRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    force = bool(payload.force) if payload else False
    permission_request_id = payload.permission_request_id if payload else None
    row, _settings, secret_globs, git_fallback_enabled = await _prepare_revert(
        db,
        file_change_id=file_change_id,
        force=force,
        permission_request_id=permission_request_id,
    )
    try:
        updated = await _revert_one(
            db,
            file_change_id=file_change_id,
            force=force,
            permission_request_id=permission_request_id,
            secret_globs=secret_globs,
            git_fallback_enabled=git_fallback_enabled,
        )
    except FileChangeError as exc:
        await db.rollback()
        raise _file_change_error_response(exc) from exc
    await db.commit()
    return {
        "file_change": serialize_file_change(updated, include_content=False),
        "restore_source": (updated.metadata_json or {}).get("restore_source", "stored_snapshot"),
    }


@router.post("/revert-batch")
async def revert_file_changes_batch_route(
    payload: BatchRevertRequest,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    fc = settings.file_changes
    secret_globs = list(fc.secret_filename_globs)
    git_fallback_enabled = bool(fc.git_fallback_enabled)
    requires_approval = bool(fc.revert_requires_approval)

    if len(payload.change_ids) > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "file_change_validation",
                "message": "Batch revert is limited to 100 file changes per call.",
                "reason": "file_change_validation",
                "details": {"requested": len(payload.change_ids), "limit": 100},
            },
        )

    # Validate every change up front; gather any that need approval gating.
    rows: list[Any] = []
    for fid in payload.change_ids:
        row = await get_file_change(db, fid)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "file_change_not_found",
                    "message": f"File change not found: {fid}",
                },
            )
        rows.append(row)

    if requires_approval and payload.permission_request_id is None:
        request, nonce = await _create_revert_permission_request(
            db, row=rows[0], force=payload.force
        )
        await event_bus.publish(
            db,
            organization_id=rows[0].organization_id,
            project_id=rows[0].project_id,
            workspace_id=rows[0].workspace_id,
            session_id=rows[0].session_id,
            agent_run_id=rows[0].agent_run_id,
            tool_call_id=rows[0].tool_call_id,
            event_type=EventType.FILE_CHANGE_BATCH_REVERT_REQUESTED,
            payload={
                "change_ids": [str(r.id) for r in rows],
                "permission_request_id": str(request.id),
                "force": bool(payload.force),
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=202,
            detail={
                "error": "permission_pending",
                "code": "permission_pending",
                "message": "Batch revert is permissioned. Approve the request and retry.",
                "status": "waiting_permission",
                "permission_request_id": str(request.id),
                "approval_nonce": nonce,
                "change_ids": [str(r.id) for r in rows],
            },
        )

    if requires_approval and payload.permission_request_id is not None:
        for row in rows:
            try:
                await _verify_revert_approval(
                    db,
                    row=row,
                    permission_request_id=payload.permission_request_id,
                    force=payload.force,
                )
            except FileChangeError as exc:
                await db.rollback()
                raise _file_change_error_response(exc) from exc
        await event_bus.publish(
            db,
            organization_id=rows[0].organization_id,
            project_id=rows[0].project_id,
            workspace_id=rows[0].workspace_id,
            session_id=rows[0].session_id,
            agent_run_id=rows[0].agent_run_id,
            tool_call_id=rows[0].tool_call_id,
            event_type=EventType.FILE_CHANGE_BATCH_REVERT_REQUESTED,
            payload={
                "change_ids": [str(r.id) for r in rows],
                "permission_request_id": str(payload.permission_request_id),
                "force": bool(payload.force),
            },
        )

    try:
        result = await revert_file_changes_batch(
            db,
            file_change_ids=[r.id for r in rows],
            workspace_root=settings.runtime.workspace_root,
            actor_user_id=None,
            force=payload.force,
            permission_request_id=payload.permission_request_id,
            secret_globs=secret_globs,
            git_fallback_enabled=git_fallback_enabled,
        )
    except FileChangeError as exc:
        await db.rollback()
        raise _file_change_error_response(exc) from exc
    await db.commit()

    if result.error:
        await event_bus.publish(
            db,
            organization_id=rows[0].organization_id,
            project_id=rows[0].project_id,
            workspace_id=rows[0].workspace_id,
            session_id=rows[0].session_id,
            agent_run_id=rows[0].agent_run_id,
            tool_call_id=rows[0].tool_call_id,
            event_type=EventType.FILE_CHANGE_BATCH_REVERT_FAILED,
            severity="error",
            payload={
                "change_ids": [str(r.id) for r in rows],
                "error": result.error,
                "restored_from_snapshots": result.restored_from_snapshots,
            },
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "file_change_batch_revert_failed",
                "message": result.error,
                "reason": "file_change_batch_revert_failed",
                "details": {
                    "reverted": [str(fid) for fid in result.reverted],
                    "skipped": result.skipped,
                    "failed": result.failed,
                    "restored_from_snapshots": result.restored_from_snapshots,
                },
            },
        )

    if result.skipped:
        # Validate-all-before-apply found unsafe changes; reject the whole batch.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "file_change_batch_rejected",
                "message": "One or more file changes are not revertible; the batch was rejected.",
                "reason": "file_change_batch_rejected",
                "details": {
                    "skipped": result.skipped,
                    "reverted": [str(fid) for fid in result.reverted],
                },
            },
        )

    await event_bus.publish(
        db,
        organization_id=rows[0].organization_id,
        project_id=rows[0].project_id,
        workspace_id=rows[0].workspace_id,
        session_id=rows[0].session_id,
        agent_run_id=rows[0].agent_run_id,
        tool_call_id=rows[0].tool_call_id,
        event_type=EventType.FILE_CHANGE_BATCH_REVERTED,
        payload={
            "change_ids": [str(r.id) for r in rows],
            "force": bool(payload.force),
            "restored_from_snapshots": result.restored_from_snapshots,
        },
    )

    return {
        "reverted": [str(fid) for fid in result.reverted],
        "skipped": result.skipped,
        "failed": result.failed,
        "restored_from_snapshots": result.restored_from_snapshots,
    }


test_router = APIRouter(prefix="/test-endpoints", tags=["test-endpoints"])


@test_router.post("/file-change-write")
async def test_file_change_write(
    payload: _TestWriteRequest,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Test-only write endpoint used by the end-to-end smoke.

    Gated by ``enable_test_endpoints`` (production always refuses). Writes
    a real file, captures a :class:`FileChange` row through the same code
    path that the tool executor uses, and returns the change id.

    Never use this endpoint in production. Production guards reject this
    route in :func:`_validate_production` because ``enable_test_endpoints``
    must be false in production.
    """
    settings = get_settings()
    if not settings.app.enable_test_endpoints:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "Test endpoints are disabled."},
        )
    workspace_root = settings.runtime.workspace_root
    target = resolve_workspace_path(workspace_root, payload.path)
    if not is_inside(workspace_root, target):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "file_change_forbidden",
                "message": "Test endpoint write path is outside the workspace root.",
            },
        )
    if payload.tool_name not in FILE_CHANGE_TOOLS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "file_change_validation",
                "message": f"Unsupported tool_name for test endpoint: {payload.tool_name}",
            },
        )

    before_bytes = payload.before_content.encode("utf-8") if payload.before_content else None
    before_sha = payload.before_sha256 or (
        hashlib.sha256(before_bytes).hexdigest() if before_bytes is not None else None
    )
    if payload.before_content is not None and target.exists() is False:
        atomic_write_text(target, payload.before_content)
    elif payload.before_content is not None and target.exists():
        try:
            current = target.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != payload.before_content:
            atomic_write_text(target, payload.before_content)

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, payload.content)

    after_sha = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    relative = target.relative_to(workspace_root).as_posix()
    diff = "".join(
        difflib.unified_diff(
            (payload.before_content or "").splitlines(keepends=True),
            payload.content.splitlines(keepends=True),
            fromfile=relative,
            tofile=relative,
        )
    ) or None
    metadata_payload = {
        "created": payload.before_content is None,
        "previous_sha256": before_sha,
        "sha256": after_sha,
        "test_endpoint": True,
    }

    org = await db.get(Organization, payload.organization_id) if payload.organization_id else None
    if org is None:
        org_row = (await db.scalars(select(Organization).limit(1))).first()
        if org_row is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "test_endpoint_no_organization", "message": "Bootstrap organization is missing."},
            )
        org = org_row
        project = (await db.scalars(select(Project).where(Project.organization_id == org.id).limit(1))).first()
        workspace = (await db.scalars(select(Workspace).where(Workspace.project_id == project.id).limit(1))).first()
        session = (await db.scalars(select(Session).where(Session.workspace_id == workspace.id).limit(1))).first()
    else:
        project = await db.get(Project, payload.project_id) if payload.project_id else None
        if project is None:
            project = (await db.scalars(select(Project).where(Project.organization_id == org.id).limit(1))).first()
        workspace = await db.get(Workspace, payload.workspace_id) if payload.workspace_id else None
        if workspace is None:
            workspace = (await db.scalars(select(Workspace).where(Workspace.project_id == project.id).limit(1))).first()
        session = await db.get(Session, payload.session_id) if payload.session_id else None
        if session is None:
            session = (await db.scalars(select(Session).where(Session.workspace_id == workspace.id).limit(1))).first()

    ctx = FileChangeContext(
        organization_id=org.id,
        project_id=project.id,
        workspace_id=workspace.id,
        session_id=session.id,
        agent_run_id=None,
        tool_call_id=None,
        workspace_root=workspace_root,
    )
    rows = await capture_for_tool_call(
        db,
        ctx=ctx,
        tool_name=payload.tool_name,
        input_json={"path": payload.path, "content": payload.content},
        result_output={"path": payload.path, "sha256": after_sha, "created": metadata_payload["created"]},
        result_metadata=metadata_payload,
        settings_snapshot={
            "enabled": True,
            "capture_content": True,
            "capture_diff": True,
            "max_content_bytes": int(settings.file_changes.max_content_bytes),
            "max_diff_bytes": int(settings.file_changes.max_diff_bytes),
            "secret_filename_globs": list(settings.file_changes.secret_filename_globs),
        },
    )
    await db.commit()
    if not rows:
        raise HTTPException(
            status_code=500,
            detail={"error": "test_endpoint_no_capture", "message": "File change capture produced no rows."},
        )
    return {
        "file_change_id": str(rows[0].id),
        "relative_path": relative,
        "after_sha256": after_sha,
        "before_sha256": before_sha,
        "diff": diff,
    }


__all__ = ["router", "test_router"]
