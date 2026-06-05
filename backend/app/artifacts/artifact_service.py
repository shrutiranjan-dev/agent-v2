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
    result = await db.scalars(_artifact_list_query(session_id=session_id, limit=limit))
    return list(result.all())
