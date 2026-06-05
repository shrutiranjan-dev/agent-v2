from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.postgres import postgres_health


async def pgvector_health() -> dict[str, str]:
    return await postgres_health()


async def pgvector_extension_status(db: AsyncSession) -> dict[str, str]:
    result = await db.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
    return {"status": "ok" if result else "degraded", "extension": "vector"}
