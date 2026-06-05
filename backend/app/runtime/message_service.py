from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.db.models import Message, Session
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.message_parts import text_part, tool_result_part, validate_message_parts
from backend.app.runtime.session_service import serialize_message


class MessageService:
    async def create_assistant(
        self,
        db: AsyncSession,
        *,
        session: Session,
        content: str,
        parts: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            role="assistant",
            content=content,
            parts=validate_message_parts(parts or [text_part(content)]),
            metadata_json=metadata or {},
        )
        db.add(message)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            event_type=EventType.MESSAGE_CREATED,
            payload={"message": serialize_message(message)},
        )
        return message

    async def create_tool_result(
        self,
        db: AsyncSession,
        *,
        session: Session,
        tool_name: str,
        content: str,
        metadata: dict[str, Any],
    ) -> Message:
        message = Message(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            role="tool",
            content=content,
            parts=validate_message_parts([tool_result_part(tool_name, content)]),
            metadata_json=metadata,
        )
        db.add(message)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            event_type=EventType.MESSAGE_CREATED,
            payload={"message": serialize_message(message)},
        )
        return message


message_service = MessageService()
