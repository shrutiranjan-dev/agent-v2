from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.postgres import get_session
from backend.app.runtime.event_bus import event_bus

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(
    websocket: WebSocket,
    session_id: UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    await event_bus.subscribe(websocket, session_id=session_id)
    try:
        await event_bus.replay_session_events(db, websocket, session_id=session_id)
        await db.commit()
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await event_bus.unsubscribe(websocket, session_id=session_id)
    except Exception:
        await event_bus.unsubscribe(websocket, session_id=session_id)
        raise
