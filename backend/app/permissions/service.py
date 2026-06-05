from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import AgentRun, AuditLog, PermissionRequest, Session, ToolCall
from backend.app.permissions.models import PermissionRequestCreate, PermissionStatus
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.loop_guard import input_hash
from backend.app.runtime.message_service import message_service
from backend.app.tools.registry import tool_registry


class PermissionStateError(RuntimeError):
    pass


class PermissionResumeSecurityError(RuntimeError):
    pass


@dataclass
class PermissionResumeContext:
    request: PermissionRequest
    tool_call: ToolCall
    run: AgentRun
    session: Session


class PermissionService:
    async def create_request(self, db: AsyncSession, data: PermissionRequestCreate) -> PermissionRequest:
        request = PermissionRequest(
            organization_id=data.organization_id,
            project_id=data.project_id,
            workspace_id=data.workspace_id,
            session_id=data.session_id,
            agent_run_id=data.agent_run_id,
            tool_call_id=data.tool_call_id,
            permission_key=data.permission_key,
            resource=data.resource,
            action="ask",
            status=PermissionStatus.PENDING,
            input_json=data.input_json,
            metadata_json=data.metadata_json,
            requested_by_user_id=data.requested_by_user_id,
        )
        db.add(request)
        await db.flush()
        db.add(
            AuditLog(
                organization_id=data.organization_id,
                actor_user_id=data.requested_by_user_id,
                action="permission.request",
                resource_type="permission_request",
                resource_id=str(request.id),
                status="pending",
                metadata_json=redact_data({
                    "permission_key": data.permission_key,
                    "resource": data.resource,
                    "tool_call_id": str(data.tool_call_id) if data.tool_call_id else None,
                }),
            )
        )
        metadata = request.metadata_json or {}
        await event_bus.publish(
            db,
            organization_id=data.organization_id,
            project_id=data.project_id,
            workspace_id=data.workspace_id,
            session_id=data.session_id,
            agent_run_id=data.agent_run_id,
            tool_call_id=data.tool_call_id,
            event_type=EventType.PERMISSION_REQUESTED,
            payload={
                "id": str(request.id),
                "permission_request_id": str(request.id),
                "permission_key": request.permission_key,
                "resource": request.resource,
                "tool_call_id": str(request.tool_call_id) if request.tool_call_id else None,
                "tool": metadata.get("tool"),
                "reason": metadata.get("reason"),
                "risk_level": metadata.get("risk_level"),
                "input": redact_data(request.input_json),
                "metadata": redact_data(metadata),
            },
        )
        return request

    async def list_pending(
        self, db: AsyncSession, *, organization_id: UUID | None = None, session_id: UUID | None = None
    ) -> list[PermissionRequest]:
        stmt = select(PermissionRequest).where(PermissionRequest.status == "pending")
        if organization_id:
            stmt = stmt.where(PermissionRequest.organization_id == organization_id)
        if session_id:
            stmt = stmt.where(PermissionRequest.session_id == session_id)
        return list((await db.scalars(stmt.order_by(PermissionRequest.created_at.desc()))).all())

    async def approve(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        user_id: UUID | None,
        message: str | None = None,
    ) -> PermissionResumeContext:
        context = await self._load_resume_context(db, request_id, required_status=PermissionStatus.PENDING)
        request = context.request
        request.status = PermissionStatus.APPROVED
        request.resolved_by_user_id = user_id
        request.resolved_at = datetime.now(UTC)
        request.resolution_message = message
        db.add(
            AuditLog(
                organization_id=request.organization_id,
                actor_user_id=user_id,
                action="permission.approve",
                resource_type="permission_request",
                resource_id=str(request.id),
                status=request.status,
                metadata_json=redact_data({"permission_key": request.permission_key, "resource": request.resource}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.PERMISSION_APPROVED,
            payload={"id": str(request.id), "permission_request_id": str(request.id), "message": message},
        )
        return context

    async def deny(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        user_id: UUID | None,
        message: str | None = None,
    ) -> PermissionResumeContext:
        context = await self._load_resume_context(
            db,
            request_id,
            required_status=PermissionStatus.PENDING,
            require_registered_tool=False,
        )
        request = context.request
        request.status = PermissionStatus.DENIED
        request.resolved_by_user_id = user_id
        request.resolved_at = datetime.now(UTC)
        request.resolution_message = message
        reason = redact_text(message or f"Permission denied for {request.permission_key}: {request.resource}")
        context.tool_call.status = "denied"
        context.tool_call.error = reason
        context.tool_call.completed_at = datetime.now(UTC)
        context.tool_call.duration_ms = 0
        context.run.status = "failed"
        context.run.error = reason
        context.run.completed_at = datetime.now(UTC)
        context.session.status = "failed"
        db.add(
            AuditLog(
                organization_id=request.organization_id,
                actor_user_id=user_id,
                action="permission.deny",
                resource_type="permission_request",
                resource_id=str(request.id),
                status=request.status,
                metadata_json=redact_data({"permission_key": request.permission_key, "resource": request.resource}),
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
                "permission_request_id": str(request.id),
            },
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.PERMISSION_DENIED,
            severity="warning",
            payload={"id": str(request.id), "permission_request_id": str(request.id), "message": message},
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.TOOL_CALL_FAILED,
            severity="warning",
            payload={"id": str(context.tool_call.id), "tool": context.tool_call.tool_name, "error": reason},
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.AGENT_RUN_FAILED,
            severity="warning",
            payload={"id": str(context.run.id), "error": reason},
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.AGENT_RUN_BLOCKED,
            severity="warning",
            payload={"id": str(context.run.id), "error": reason, "permission_request_id": str(request.id)},
        )
        return context

    async def load_approved_resume_context(self, db: AsyncSession, *, request_id: UUID) -> PermissionResumeContext:
        return await self._load_resume_context(db, request_id, required_status=PermissionStatus.APPROVED)

    async def resolve(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        approved: bool,
        user_id: UUID | None,
        message: str | None = None,
    ) -> PermissionRequest:
        if approved:
            return (await self.approve(db, request_id=request_id, user_id=user_id, message=message)).request
        return (await self.deny(db, request_id=request_id, user_id=user_id, message=message)).request

    async def _load_resume_context(
        self,
        db: AsyncSession,
        request_id: UUID,
        *,
        required_status: PermissionStatus,
        require_registered_tool: bool = True,
    ) -> PermissionResumeContext:
        request = await db.get(PermissionRequest, request_id)
        if not request:
            raise KeyError(f"Permission request not found: {request_id}")
        if request.status != required_status:
            if required_status == PermissionStatus.PENDING:
                raise PermissionStateError(f"Permission request {request_id} is already {request.status}.")
            raise PermissionStateError(
                f"Permission request {request_id} must be {required_status}; current status is {request.status}."
            )
        if not request.tool_call_id or not request.agent_run_id:
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="permission request is not linked to a tool call and agent run",
            )
            raise PermissionResumeSecurityError("Permission request is missing linked runtime rows.")

        tool_call = await db.get(ToolCall, request.tool_call_id)
        run = await db.get(AgentRun, request.agent_run_id)
        session = await db.get(Session, request.session_id)
        if not tool_call or not run or not session:
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="linked tool call, agent run, or session is missing",
            )
            raise PermissionResumeSecurityError("Permission request linked runtime rows are missing.")
        if tool_call.permission_request_id != request.id or tool_call.status != "waiting_permission":
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="linked tool call is not waiting for this permission request",
                tool_call_id=tool_call.id,
            )
            raise PermissionResumeSecurityError("Linked tool call is not waiting for this permission request.")
        stored_hash = str((request.metadata_json or {}).get("input_hash") or "")
        current_hash = input_hash(request.input_json)
        if not stored_hash or stored_hash != tool_call.input_hash or current_hash != tool_call.input_hash:
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="permission request input hash does not match linked tool call",
                tool_call_id=tool_call.id,
            )
            raise PermissionResumeSecurityError("Permission request input hash mismatch.")
        if tool_call.input_json != request.input_json:
            await self._publish_resume_blocked(
                db,
                request=request,
                reason="permission request input payload does not match linked tool call",
                tool_call_id=tool_call.id,
            )
            raise PermissionResumeSecurityError("Permission request input payload mismatch.")
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
                raise PermissionResumeSecurityError("Tool is no longer registered.") from exc
        return PermissionResumeContext(request=request, tool_call=tool_call, run=run, session=session)

    async def _publish_resume_blocked(
        self,
        db: AsyncSession,
        *,
        request: PermissionRequest,
        reason: str,
        tool_call_id: UUID | None = None,
    ) -> None:
        db.add(
            AuditLog(
                organization_id=request.organization_id,
                actor_user_id=None,
                action="permission.resume_blocked",
                resource_type="permission_request",
                resource_id=str(request.id),
                status="blocked",
                metadata_json=redact_data({"reason": reason, "permission_key": request.permission_key}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=tool_call_id or request.tool_call_id,
            event_type=EventType.PERMISSION_RESUME_BLOCKED,
            severity="error",
            payload={"id": str(request.id), "reason": reason},
        )


permission_service = PermissionService()
