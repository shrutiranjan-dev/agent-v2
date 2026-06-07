from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.postgres import get_session
from backend.app.file_changes.file_change_service import (
    FileChangeError,
    FileChangeNotRevertible,
    get_file_change,
    list_file_changes,
    revert_file_change,
    serialize_file_change,
)
from backend.app.permissions.policy import PermissionAction, secret_path_action
from backend.app.tools.base import is_inside

router = APIRouter(prefix="/file-changes", tags=["file-changes"])


class RevertRequest(BaseModel):
    force: bool = False


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
        raise HTTPException(status_code=404, detail=f"File change not found: {file_change_id}")
    return {"file_change": serialize_file_change(row, include_content=include_content)}


@router.post("/{file_change_id}/revert")
async def revert_file_change_route(
    file_change_id: UUID,
    payload: RevertRequest | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    force = bool(payload.force) if payload else False
    workspace_root = get_settings().runtime.workspace_root
    row = await get_file_change(db, file_change_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"File change not found: {file_change_id}")
    if row.revert_status == "reverted":
        raise HTTPException(
            status_code=409,
            detail=f"File change {file_change_id} is already reverted.",
        )
    if row.redacted or not row.revertible:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Revert denied: {row.redaction_reason or 'redacted file'}."
            ),
        )
    relative = _safe_relative_path(row.resolved_path, workspace_root)
    if relative is None:
        raise HTTPException(
            status_code=422,
            detail=f"File change path is outside the workspace root: {row.resolved_path}",
        )
    secret_action = secret_path_action(Path(relative))
    if secret_action == PermissionAction.DENY:
        raise HTTPException(
            status_code=403,
            detail="Revert denied: file matches a private-key or secret file pattern.",
        )
    if secret_action == PermissionAction.ASK and not force:
        raise HTTPException(
            status_code=409,
            detail="Revert requires explicit force=true for secret-like files.",
        )
    try:
        updated = await revert_file_change(
            db,
            file_change_id=file_change_id,
            workspace_root=workspace_root,
            actor_user_id=None,
            force=force,
        )
    except FileChangeNotRevertible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileChangeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"file_change": serialize_file_change(updated, include_content=False)}


__all__ = ["router"]
