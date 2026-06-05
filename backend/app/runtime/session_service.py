from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.registry import agent_registry
from backend.app.core.errors import NotFoundError
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.core.security import TenantContext
from backend.app.db.models import Message, Session, SessionSummary, ToolCall
from backend.app.memory.summary_service import serialize_summary
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.message_parts import text_part, validate_message_parts
from backend.app.runtime.tenant import RuntimeTenant, ensure_runtime_tenant


class SessionCreate(BaseModel):
    title: str | None = None
    agent_id: str = "build"
    model_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserMessageCreate(BaseModel):
    content: str
    agent_id: str | None = None
    model_name: str | None = None


class SessionResponse(BaseModel):
    id: str
    organization_id: str
    project_id: str
    workspace_id: str
    title: str
    agent_id: str
    model_provider: str
    model_name: str
    status: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    parts: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: str


class ToolCallResponse(BaseModel):
    id: str
    session_id: str
    agent_run_id: str | None
    agent_id: str
    tool_name: str
    input: dict[str, Any]
    status: str
    output: dict[str, Any] | None
    error: str | None
    permission_request_id: str | None
    duration_ms: int | None
    created_at: str


class SessionDetailResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    tool_calls: list[ToolCallResponse]
    summaries: list[dict[str, Any]] = Field(default_factory=list)


def serialize_session(session: Session) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "organization_id": str(session.organization_id),
        "project_id": str(session.project_id),
        "workspace_id": str(session.workspace_id),
        "title": session.title,
        "agent_id": session.agent_id,
        "model_provider": session.model_provider,
        "model_name": session.model_name,
        "status": session.status,
        "metadata": session.metadata_json,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def serialize_message(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "session_id": str(message.session_id),
        "role": message.role,
        "content": redact_text(message.content),
        "parts": redact_data(message.parts),
        "metadata": redact_data(message.metadata_json),
        "created_at": message.created_at.isoformat(),
    }


def serialize_tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "session_id": str(call.session_id),
        "agent_run_id": str(call.agent_run_id) if call.agent_run_id else None,
        "agent_id": call.agent_id,
        "tool_name": call.tool_name,
        "input": redact_data(call.input_json),
        "status": call.status,
        "output": redact_data(call.output_json),
        "error": redact_text(call.error) if call.error else None,
        "permission_request_id": str(call.permission_request_id) if call.permission_request_id else None,
        "duration_ms": call.duration_ms,
        "created_at": call.created_at.isoformat(),
    }


class SessionService:
    async def create(
        self, db: AsyncSession, tenant_ctx: TenantContext, payload: SessionCreate
    ) -> tuple[RuntimeTenant, Session]:
        tenant = await ensure_runtime_tenant(db, tenant_ctx)
        agent = agent_registry.get(payload.agent_id)
        session = Session(
            organization_id=tenant.organization_id,
            project_id=tenant.project_id,
            workspace_id=tenant.workspace_id,
            created_by_user_id=tenant.user_id,
            title=payload.title or f"New session - {datetime.now(UTC).isoformat()}",
            agent_id=agent.id,
            model_provider="ollama",
            model_name=payload.model_name or agent.llm.model,
            metadata_json=payload.metadata,
        )
        db.add(session)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=tenant.organization_id,
            project_id=tenant.project_id,
            workspace_id=tenant.workspace_id,
            session_id=session.id,
            event_type=EventType.SESSION_CREATED,
            payload={"session": serialize_session(session)},
        )
        return tenant, session

    async def list(self, db: AsyncSession, tenant_ctx: TenantContext) -> list[Session]:
        tenant = await ensure_runtime_tenant(db, tenant_ctx)
        rows = await db.scalars(
            select(Session)
            .where(Session.organization_id == tenant.organization_id)
            .order_by(Session.updated_at.desc())
            .limit(100)
        )
        return list(rows.all())

    async def get(self, db: AsyncSession, session_id: UUID, tenant_ctx: TenantContext | None = None) -> Session:
        session = await db.get(Session, session_id)
        if not session:
            raise NotFoundError(f"Session not found: {session_id}")
        if tenant_ctx:
            tenant = await ensure_runtime_tenant(db, tenant_ctx)
            if session.organization_id != tenant.organization_id:
                raise NotFoundError(f"Session not found: {session_id}")
        return session

    async def detail(self, db: AsyncSession, session_id: UUID, tenant_ctx: TenantContext | None = None) -> dict[str, Any]:
        session = await self.get(db, session_id, tenant_ctx=tenant_ctx)
        messages = list(
            (
                await db.scalars(
                    select(Message)
                    .where(Message.session_id == session_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
            ).all()
        )
        tool_calls = list(
            (
                await db.scalars(
                    select(ToolCall)
                    .where(ToolCall.session_id == session_id)
                    .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
                )
            ).all()
        )
        summaries = list(
            (
                await db.scalars(
                    select(SessionSummary)
                    .where(SessionSummary.session_id == session_id, SessionSummary.status == "active")
                    .order_by(SessionSummary.created_at.asc(), SessionSummary.id.asc())
                )
            ).all()
        )
        data = {
            "session": serialize_session(session),
            "messages": [serialize_message(message) for message in messages],
            "tool_calls": [serialize_tool_call(call) for call in tool_calls],
            "summaries": [serialize_summary(summary) for summary in summaries],
        }
        SessionDetailResponse.model_validate(data)
        return data

    async def add_user_message(
        self,
        db: AsyncSession,
        *,
        session: Session,
        content: str,
        agent_id: str | None = None,
        model_name: str | None = None,
    ) -> Message:
        if agent_id:
            agent_registry.get(agent_id)
            session.agent_id = agent_id
        if model_name:
            session.model_name = model_name
        message = Message(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            role="user",
            content=content,
            parts=validate_message_parts([text_part(content)]),
            metadata_json={"agent_id": session.agent_id, "model_name": session.model_name},
        )
        session.status = "running"
        session.updated_at = datetime.now(UTC)
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


session_service = SessionService()
