from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import AgentRun, AuditLog, HumanInputRequest, Session, ToolCall
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.loop_guard import input_hash
from backend.app.runtime.message_service import message_service
from backend.app.tools.base import ToolResult
from backend.app.tools.registry import tool_registry


class HumanInputStateError(RuntimeError):
    pass


class HumanInputValidationError(ValueError):
    pass


class HumanInputResumeSecurityError(RuntimeError):
    pass


class HumanInputRequestCreate(BaseModel):
    organization_id: UUID
    project_id: UUID
    workspace_id: UUID
    session_id: UUID
    run_id: UUID
    tool_call_id: UUID
    question: str
    details: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    request_hash: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


@dataclass
class HumanInputResumeContext:
    request: HumanInputRequest
    tool_call: ToolCall
    run: AgentRun
    session: Session


class HumanInputService:
    async def create_request(self, db: AsyncSession, data: HumanInputRequestCreate) -> HumanInputRequest:
        request = HumanInputRequest(
            organization_id=data.organization_id,
            project_id=data.project_id,
            workspace_id=data.workspace_id,
            session_id=data.session_id,
            run_id=data.run_id,
            tool_call_id=data.tool_call_id,
            question=data.question,
            details_json=data.details,
            status="pending",
            expires_at=data.expires_at,
            request_hash=data.request_hash,
            metadata_json=data.metadata_json,
        )
        db.add(request)
        await db.flush()
        db.add(
            AuditLog(
                organization_id=data.organization_id,
                actor_user_id=None,
                action="human_input.request",
                resource_type="human_input_request",
                resource_id=str(request.id),
                status="pending",
                metadata_json=redact_data({
                    "tool_call_id": str(data.tool_call_id),
                    "run_id": str(data.run_id),
                    "question": data.question,
                }),
            )
        )
        await event_bus.publish(
            db,
            organization_id=data.organization_id,
            project_id=data.project_id,
            workspace_id=data.workspace_id,
            session_id=data.session_id,
            agent_run_id=data.run_id,
            tool_call_id=data.tool_call_id,
            event_type=EventType.QUESTION_REQUESTED,
            payload=serialize_human_input_request(request),
        )
        return request

    async def list_requests(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID | None = None,
        session_id: UUID | None = None,
        status: str | None = None,
    ) -> list[HumanInputRequest]:
        if hasattr(db, "objects"):
            rows = [
                row
                for (model, _row_id), row in db.objects.items()
                if model is HumanInputRequest
                and (organization_id is None or row.organization_id == organization_id)
                and (session_id is None or row.session_id == session_id)
                and (status is None or row.status == status)
            ]
            return sorted(rows, key=lambda item: item.created_at, reverse=True)
        stmt = select(HumanInputRequest)
        if organization_id:
            stmt = stmt.where(HumanInputRequest.organization_id == organization_id)
        if session_id:
            stmt = stmt.where(HumanInputRequest.session_id == session_id)
        if status:
            stmt = stmt.where(HumanInputRequest.status == status)
        return list((await db.scalars(stmt.order_by(HumanInputRequest.created_at.desc()))).all())

    async def answer(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        answer: str,
        user_id: UUID | None,
    ) -> HumanInputResumeContext:
        context = await self._load_resume_context(db, request_id, required_status="pending")
        request = context.request
        await self._expire_if_needed(db, request=request, context=context)
        metadata = request.metadata_json or {}
        choices = list(metadata.get("choices") or [])
        allow_free_text = bool(metadata.get("allow_free_text", True))
        if choices and not allow_free_text and answer not in choices:
            raise HumanInputValidationError("Answer must be one of the provided choices.")

        request.status = "answered"
        request.answer = answer
        request.answered_by_user_id = user_id
        request.answered_at = datetime.now(UTC)
        db.add(
            AuditLog(
                organization_id=request.organization_id,
                actor_user_id=user_id,
                action="human_input.answer",
                resource_type="human_input_request",
                resource_id=str(request.id),
                status="answered",
                metadata_json=redact_data({"question": request.question, "answer": answer}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.QUESTION_ANSWERED,
            payload={
                **serialize_human_input_request(request),
                "answer": redact_text(answer),
                "answered_by": str(user_id) if user_id else None,
            },
        )
        return context

    async def cancel(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        user_id: UUID | None,
        message: str | None = None,
    ) -> HumanInputResumeContext:
        context = await self._load_resume_context(db, request_id, required_status="pending", require_registered_tool=False)
        reason = redact_text(message or "Human input request was cancelled.")
        request = context.request
        request.status = "cancelled"
        request.cancelled_at = datetime.now(UTC)
        context.tool_call.status = "cancelled"
        context.tool_call.error = reason
        context.tool_call.completed_at = datetime.now(UTC)
        context.tool_call.duration_ms = 0
        context.tool_call.output_json = ToolResult.failure(
            code="human_input_cancelled",
            message=reason,
            recoverable=False,
            metadata={"human_input_request_id": str(request.id)},
        ).model_dump(mode="json")
        context.run.status = "cancelled"
        context.run.error = reason
        context.run.completed_at = datetime.now(UTC)
        context.session.status = "cancelled"
        db.add(
            AuditLog(
                organization_id=request.organization_id,
                actor_user_id=user_id,
                action="human_input.cancel",
                resource_type="human_input_request",
                resource_id=str(request.id),
                status="cancelled",
                metadata_json=redact_data({"reason": reason}),
            )
        )
        await message_service.create_assistant(
            db,
            session=context.session,
            content=reason,
            metadata={
                "error": True,
                "agent_run_id": str(context.run.id),
                "tool_call_id": str(context.tool_call.id),
                "human_input_request_id": str(request.id),
            },
        )
        await self._publish_terminal_question_event(db, context=context, event_type=EventType.QUESTION_CANCELLED, reason=reason)
        return context

    async def expire_request(self, db: AsyncSession, *, request_id: UUID) -> HumanInputResumeContext:
        context = await self._load_resume_context(db, request_id, required_status="pending", require_registered_tool=False)
        reason = "Human input request expired."
        request = context.request
        request.status = "expired"
        context.tool_call.status = "failed"
        context.tool_call.error = reason
        context.tool_call.completed_at = datetime.now(UTC)
        context.tool_call.duration_ms = 0
        context.tool_call.output_json = ToolResult.failure(
            code="human_input_expired",
            message=reason,
            recoverable=True,
            metadata={"human_input_request_id": str(request.id)},
        ).model_dump(mode="json")
        context.run.status = "failed"
        context.run.error = reason
        context.run.completed_at = datetime.now(UTC)
        context.session.status = "failed"
        await message_service.create_assistant(
            db,
            session=context.session,
            content=reason,
            metadata={
                "error": True,
                "agent_run_id": str(context.run.id),
                "tool_call_id": str(context.tool_call.id),
                "human_input_request_id": str(request.id),
            },
        )
        await self._publish_terminal_question_event(db, context=context, event_type=EventType.QUESTION_EXPIRED, reason=reason)
        return context

    async def expire_pending(self, db: AsyncSession, *, now: datetime | None = None) -> list[HumanInputRequest]:
        now = now or datetime.now(UTC)
        pending = await self.list_requests(db, status="pending")
        expired: list[HumanInputRequest] = []
        for request in pending:
            if request.expires_at and request.expires_at <= now:
                await self.expire_request(db, request_id=request.id)
                expired.append(request)
        return expired

    async def load_answered_resume_context(self, db: AsyncSession, *, request_id: UUID) -> HumanInputResumeContext:
        return await self._load_resume_context(db, request_id, required_status="answered")

    async def _expire_if_needed(
        self,
        db: AsyncSession,
        *,
        request: HumanInputRequest,
        context: HumanInputResumeContext,
    ) -> None:
        if request.expires_at and request.expires_at <= datetime.now(UTC):
            await self.expire_request(db, request_id=request.id)
            raise HumanInputStateError(f"Human input request {request.id} has expired.")
        _ = context

    async def _load_resume_context(
        self,
        db: AsyncSession,
        request_id: UUID,
        *,
        required_status: str,
        require_registered_tool: bool = True,
    ) -> HumanInputResumeContext:
        request = await db.get(HumanInputRequest, request_id)
        if not request:
            raise KeyError(f"Human input request not found: {request_id}")
        if request.status != required_status:
            raise HumanInputStateError(
                f"Human input request {request_id} must be {required_status}; current status is {request.status}."
            )
        tool_call = await db.get(ToolCall, request.tool_call_id)
        run = await db.get(AgentRun, request.run_id)
        session = await db.get(Session, request.session_id)
        if not tool_call or not run or not session:
            await self._publish_resume_blocked(db, request=request, reason="linked tool call, run, or session is missing")
            raise HumanInputResumeSecurityError("Human input request linked runtime rows are missing.")
        if tool_call.status != "waiting_human_input":
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="linked tool call is not waiting for human input",
                tool_call_id=tool_call.id,
            )
            raise HumanInputResumeSecurityError("Linked tool call is not waiting for human input.")
        if tool_call.tool_name != "question.ask":
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="linked tool call is not question.ask",
                tool_call_id=tool_call.id,
            )
            raise HumanInputResumeSecurityError("Linked tool call is not question.ask.")
        current_hash = input_hash(tool_call.input_json)
        if not request.request_hash or request.request_hash != tool_call.input_hash or current_hash != tool_call.input_hash:
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="human input request hash does not match linked tool call",
                tool_call_id=tool_call.id,
            )
            raise HumanInputResumeSecurityError("Human input request hash mismatch.")
        if require_registered_tool:
            try:
                tool_registry.get(tool_call.tool_name)
            except Exception as exc:
                await self._publish_resume_blocked(
                    db,
                    request=request,
                    reason=f"registered tool missing at resume time: {exc}",
                    tool_call_id=tool_call.id,
                )
                raise HumanInputResumeSecurityError("Tool is no longer registered.") from exc
        return HumanInputResumeContext(request=request, tool_call=tool_call, run=run, session=session)

    async def _publish_resume_blocked(
        self,
        db: AsyncSession,
        *,
        request: HumanInputRequest,
        reason: str,
        tool_call_id: UUID | None = None,
    ) -> None:
        db.add(
            AuditLog(
                organization_id=request.organization_id,
                actor_user_id=None,
                action="human_input.resume_blocked",
                resource_type="human_input_request",
                resource_id=str(request.id),
                status="blocked",
                metadata_json=redact_data({"reason": reason}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.run_id,
            tool_call_id=tool_call_id or request.tool_call_id,
            event_type=EventType.QUESTION_RESUME_BLOCKED,
            severity="error",
            payload={"id": str(request.id), "human_input_request_id": str(request.id), "reason": reason},
        )

    async def _publish_terminal_question_event(
        self,
        db: AsyncSession,
        *,
        context: HumanInputResumeContext,
        event_type: EventType,
        reason: str,
    ) -> None:
        await event_bus.publish(
            db,
            organization_id=context.request.organization_id,
            project_id=context.request.project_id,
            workspace_id=context.request.workspace_id,
            session_id=context.request.session_id,
            agent_run_id=context.request.run_id,
            tool_call_id=context.request.tool_call_id,
            event_type=event_type,
            severity="warning",
            payload={"id": str(context.request.id), "human_input_request_id": str(context.request.id), "reason": reason},
        )
        await event_bus.publish(
            db,
            organization_id=context.request.organization_id,
            project_id=context.request.project_id,
            workspace_id=context.request.workspace_id,
            session_id=context.request.session_id,
            agent_run_id=context.request.run_id,
            tool_call_id=context.request.tool_call_id,
            event_type=EventType.TOOL_CALL_FAILED,
            severity="warning",
            payload={"id": str(context.tool_call.id), "tool": context.tool_call.tool_name, "error": reason},
        )
        await event_bus.publish(
            db,
            organization_id=context.request.organization_id,
            project_id=context.request.project_id,
            workspace_id=context.request.workspace_id,
            session_id=context.request.session_id,
            agent_run_id=context.request.run_id,
            tool_call_id=context.request.tool_call_id,
            event_type=EventType.AGENT_RUN_BLOCKED,
            severity="warning",
            payload={"id": str(context.run.id), "error": reason, "human_input_request_id": str(context.request.id)},
        )


def serialize_human_input_request(row: HumanInputRequest) -> dict[str, Any]:
    metadata = row.metadata_json or {}
    return {
        "id": str(row.id),
        "human_input_request_id": str(row.id),
        "session_id": str(row.session_id),
        "run_id": str(row.run_id),
        "agent_run_id": str(row.run_id),
        "tool_call_id": str(row.tool_call_id),
        "question": redact_text(row.question),
        "details": redact_data(row.details_json),
        "status": row.status,
        "answer": redact_text(row.answer) if row.answer else None,
        "answered_by": str(row.answered_by_user_id) if row.answered_by_user_id else None,
        "choices": list(metadata.get("choices") or []),
        "allow_free_text": bool(metadata.get("allow_free_text", True)),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "metadata": redact_data(metadata),
    }


human_input_service = HumanInputService()
