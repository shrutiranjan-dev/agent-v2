from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.artifacts.artifact_service import get_artifact, list_artifacts
from backend.app.db.models import Artifact
from backend.app.db.postgres import get_session

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

SENSITIVE_METADATA_KEYS = ("api_key", "apikey", "secret", "token", "password", "private_key", "credential")


def _redact_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower().replace("-", "_")
            safe[key] = "[redacted]" if any(marker in lowered for marker in SENSITIVE_METADATA_KEYS) else _redact_metadata(item)
        return safe
    if isinstance(value, list):
        return [_redact_metadata(item) for item in value]
    return value


def serialize_artifact(row: Artifact) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "kind": row.kind,
        "session_id": str(row.session_id) if row.session_id else None,
        "tool_call_id": str(row.tool_call_id) if row.tool_call_id else None,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "checksum": row.checksum,
        "metadata": _redact_metadata(row.metadata_json or {}),
        "download_url": None,
        "download_status": "metadata_only",
        "created_at": row.created_at.isoformat(),
    }


@router.get("")
async def artifacts(
    session_id: UUID | None = None,
    limit: int = 500,
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await list_artifacts(db, session_id=session_id, limit=max(1, min(limit, 500)))
    return {
        "artifacts": [serialize_artifact(row) for row in rows],
        "download_status": "metadata_only",
    }


@router.get("/{artifact_id}")
async def artifact_detail(artifact_id: UUID, db: AsyncSession = Depends(get_session)) -> dict:
    row = await get_artifact(db, artifact_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    return {"artifact": serialize_artifact(row)}

