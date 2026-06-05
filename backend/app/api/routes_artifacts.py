from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.artifacts.artifact_service import list_artifacts
from backend.app.db.postgres import get_session

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("")
async def artifacts(db: AsyncSession = Depends(get_session)) -> dict:
    rows = await list_artifacts(db)
    return {
        "artifacts": [
            {
                "id": str(row.id),
                "name": row.name,
                "kind": row.kind,
                "bucket": row.bucket,
                "object_key": row.object_key,
                "content_type": row.content_type,
                "size_bytes": row.size_bytes,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }

