from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Artifact


def _artifact_list_query(*, session_id: UUID | None = None, limit: int = 500) -> Select[tuple[Artifact]]:
    stmt = select(Artifact).order_by(Artifact.created_at.desc()).limit(limit)
    if session_id is not None:
        stmt = stmt.where(Artifact.session_id == session_id)
    return stmt


async def list_artifacts(
    db: AsyncSession,
    *,
    session_id: UUID | None = None,
    limit: int = 500,
) -> Sequence[Artifact]:
    if hasattr(db, "objects"):
        rows = [row for (model, _row_id), row in db.objects.items() if model is Artifact]
        if session_id is not None:
            rows = [row for row in rows if row.session_id == session_id]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)[:limit]
    result = await db.scalars(_artifact_list_query(session_id=session_id, limit=limit))
    return list(result.all())


async def get_artifact(db: AsyncSession, artifact_id: UUID) -> Artifact | None:
    if hasattr(db, "objects"):
        return db.objects.get((Artifact, artifact_id))
    return await db.get(Artifact, artifact_id)
