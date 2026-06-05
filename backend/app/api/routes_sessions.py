from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.models import SystemEvent
from backend.app.db.postgres import get_session
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.session_service import SessionCreate, serialize_session, session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict:
    _, session = await session_service.create(db, tenant, payload)
    await db.commit()
    return {"session": serialize_session(session)}


@router.get("")
async def list_sessions(
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict:
    sessions = await session_service.list(db, tenant)
    await db.commit()
    return {"sessions": [serialize_session(session) for session in sessions]}


@router.get("/{session_id}")
async def get_session_detail(
    session_id: UUID,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict:
    return await session_service.detail(db, session_id, tenant_ctx=tenant)


@router.get("/{session_id}/events")
async def get_session_events(session_id: UUID, db: AsyncSession = Depends(get_session)) -> dict:
    rows = list(
        (
            await db.scalars(
                select(SystemEvent)
                .where(SystemEvent.session_id == session_id)
                .order_by(SystemEvent.created_at.asc())
                .limit(500)
            )
        ).all()
    )
    return {"events": [event_bus.serialize(row) for row in rows]}
