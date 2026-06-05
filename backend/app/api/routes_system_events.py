from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import SystemEvent
from backend.app.db.postgres import get_session
from backend.app.runtime.event_bus import event_bus

router = APIRouter(prefix="/system/events", tags=["system-events"])


@router.get("")
async def system_events(db: AsyncSession = Depends(get_session)) -> dict:
    rows = list(
        (await db.scalars(select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(500))).all()
    )
    return {"events": [event_bus.serialize(row) for row in rows]}
