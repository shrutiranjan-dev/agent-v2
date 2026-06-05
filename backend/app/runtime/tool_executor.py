from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base import AgentDefinition
from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import AuditLog, Session, ToolCall
from backend.app.permissions.models import PermissionAction, PermissionRequestCreate
from backend.app.permissions.policy import evaluate_default_policy
from backend.app.permissions.service import permission_service
from backend.app.plugins.hooks import hook_registry
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.human_input_service import HumanInputRequestCreate, human_input_service
from backend.app.runtime.loop_guard import loop_guard
from backend.app.tools.base import ToolContext
from backend.app.tools.registry import tool_registry


@dataclass
class ToolExecutionOutcome:
    status: str
    tool_call: ToolCall
    output: dict[str, Any] | None = None
    error: str | None = None
    permission_request_id: UUID | None = None
    human_input_request_id: UUID | None = None


class ToolExecutor:
    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        project_id: UUID,
        workspace_id: UUID,
        session_id: UUID,
        user_id: UUID | None,
        agent_run_id: UUID | None,
        agent: AgentDefinition,
        tool_name: str,
        input_json: dict[str, Any],
    ) -> ToolExecutionOutcome:
        try:
            tool = tool_registry.get(tool_name)
        except Exception as exc:
            error = redact_text(str(exc))
            digest = await loop_guard.assert_not_repeated(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_id=agent.id,
                tool_name=tool_name,
                input_json=input_json,
            )
            call = ToolCall(
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                agent_id=agent.id,
                tool_name=tool_name,
                input_json=input_json,
                input_hash=digest,
                status="failed",
                error=error,
                completed_at=datetime.now(UTC),
                duration_ms=0,
            )
            db.add(call)
            await db.flush()
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.TOOL_CALL_FAILED,
                severity="warning",
                payload={"id": str(call.id), "tool": tool_name, "error": call.error},
            )
            return ToolExecutionOutcome(status="failed", tool_call=call, error=call.error)
        if tool_name not in agent.allowed_tools:
            digest = await loop_guard.assert_not_repeated(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_id=agent.id,
                tool_name=tool_name,
                input_json=input_json,
            )
            error = redact_text(f"Tool {tool_name} is not allowed for agent {agent.id}.")
            call = ToolCall(
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                agent_id=agent.id,
                tool_name=tool_name,
                input_json=input_json,
                input_hash=digest,
                status="denied",
                error=error,
                completed_at=datetime.now(UTC),
                duration_ms=0,
            )
            db.add(call)
            await db.flush()
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.TOOL_CALL_FAILED,
                severity="warning",
                payload={"id": str(call.id), "tool": tool_name, "error": call.error},
            )
            return ToolExecutionOutcome(status="denied", tool_call=call, error=call.error)

        try:
            typed_input = tool.input_model.model_validate(input_json)
        except ValidationError as exc:
            digest = await loop_guard.assert_not_repeated(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_id=agent.id,
                tool_name=tool_name,
                input_json=input_json,
            )
            error = redact_text(f"Invalid tool input: {exc}")
            call = ToolCall(
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                agent_id=agent.id,
                tool_name=tool_name,
                input_json=input_json,
                input_hash=digest,
                status="failed",
                error=error,
                completed_at=datetime.now(UTC),
                duration_ms=0,
            )
            db.add(call)
            await db.flush()
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.TOOL_CALL_FAILED,
                severity="warning",
                payload={"id": str(call.id), "tool": tool_name, "error": call.error},
            )
            return ToolExecutionOutcome(status="failed", tool_call=call, error=call.error)

        digest = await loop_guard.assert_not_repeated(
            db,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent.id,
            tool_name=tool_name,
            input_json=input_json,
        )
        call = ToolCall(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_run_id=agent_run_id,
            agent_id=agent.id,
            tool_name=tool_name,
            input_json=input_json,
            input_hash=digest,
            status="pending",
        )
        db.add(call)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=call.id,
            event_type=EventType.TOOL_CALL_REQUESTED,
            payload={"id": str(call.id), "tool": tool_name, "input": input_json},
        )

        settings = get_settings()
        workspace_root = settings.workspace_root
        external_write_policy = PermissionAction(getattr(settings.runtime, "external_write_policy", "deny"))
        resource = tool.resource(typed_input, workspace_root)
        decision = evaluate_default_policy(
            permission_key=tool.permission_key,
            resource=resource,
            input_json=input_json,
            workspace_root=workspace_root,
            external_write_policy=external_write_policy,
        )
        if decision.action == PermissionAction.DENY:
            call.status = "denied"
            call.error = redact_text(decision.reason)
            call.completed_at = datetime.now(UTC)
            call.duration_ms = 0
            db.add(
                AuditLog(
                    organization_id=organization_id,
                    actor_user_id=user_id,
                    action="tool.execute",
                    resource_type="tool_call",
                    resource_id=str(call.id),
                    status="denied",
                    metadata_json=redact_data({"tool": tool_name, "reason": decision.reason}),
                )
            )
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.PERMISSION_DENIED,
                severity="warning",
                payload={"permission_key": decision.permission_key, "resource": decision.resource, "reason": decision.reason},
            )
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.TOOL_CALL_FAILED,
                severity="warning",
                payload={"id": str(call.id), "tool": tool_name, "error": decision.reason},
            )
            return ToolExecutionOutcome(status="denied", tool_call=call, error=decision.reason)

        if decision.action == PermissionAction.ASK:
            request = await permission_service.create_request(
                db,
                PermissionRequestCreate(
                    organization_id=organization_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    agent_run_id=agent_run_id,
                    tool_call_id=call.id,
                    permission_key=decision.permission_key,
                    resource=decision.resource,
                    input_json=input_json,
                    metadata_json={"tool": tool_name, "reason": decision.reason, "input_hash": digest},
                    requested_by_user_id=user_id,
                ),
            )
            call.status = "waiting_permission"
            call.permission_request_id = request.id
            await db.flush()
            return ToolExecutionOutcome(
                status="waiting_permission",
                tool_call=call,
                permission_request_id=request.id,
            )

        if tool_name == "question.ask":
            if agent_run_id is None:
                call.status = "failed"
                call.error = "question.ask requires an active agent run."
                call.completed_at = datetime.now(UTC)
                call.duration_ms = 0
                return ToolExecutionOutcome(status="failed", tool_call=call, error=call.error)
            question = str(getattr(typed_input, "question", "") or "").strip()
            if not question:
                call.status = "failed"
                call.error = "question.ask requires a question."
                call.completed_at = datetime.now(UTC)
                call.duration_ms = 0
                return ToolExecutionOutcome(status="failed", tool_call=call, error=call.error)
            timeout_seconds = getattr(typed_input, "timeout_seconds", None)
            details = getattr(typed_input, "details", None)
            if details is None:
                details_json: dict[str, Any] = {}
            elif isinstance(details, dict):
                details_json = details
            else:
                details_json = {"text": str(details)}
            choices = list(getattr(typed_input, "choices", []) or [])
            allow_free_text = bool(getattr(typed_input, "allow_free_text", True))
            expires_at = (
                datetime.now(UTC) + timedelta(seconds=int(timeout_seconds))
                if timeout_seconds
                else None
            )
            request = await human_input_service.create_request(
                db,
                HumanInputRequestCreate(
                    organization_id=organization_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    run_id=agent_run_id,
                    tool_call_id=call.id,
                    question=question,
                    details=details_json,
                    expires_at=expires_at,
                    request_hash=digest,
                    metadata_json={
                        "tool": tool_name,
                        "choices": choices,
                        "allow_free_text": allow_free_text,
                        "timeout_seconds": timeout_seconds,
                        "input_hash": digest,
                    },
                ),
            )
            call.status = "waiting_human_input"
            await db.flush()
            return ToolExecutionOutcome(
                status="waiting_human_input",
                tool_call=call,
                human_input_request_id=request.id,
            )

        call.status = "running"
        call.started_at = datetime.now(UTC)
        await event_bus.publish(
            db,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=call.id,
            event_type=EventType.TOOL_CALL_STARTED,
            payload={"id": str(call.id), "tool": tool_name, "input": input_json},
        )
        ctx = ToolContext(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=call.id,
            agent_id=agent.id,
            workspace_root=workspace_root,
            db=db,
        )
        try:
            await hook_registry.trigger(
                "before_tool_execute",
                {
                    "tool": tool_name,
                    "tool_call_id": str(call.id),
                    "session_id": str(session_id),
                    "agent_run_id": str(agent_run_id) if agent_run_id else None,
                    "input": redact_data(input_json),
                },
                db=db,
            )
            result = await tool.run_with_timeout(typed_input, ctx)
            await hook_registry.trigger(
                "after_tool_execute",
                {
                    "tool": tool_name,
                    "tool_call_id": str(call.id),
                    "session_id": str(session_id),
                    "agent_run_id": str(agent_run_id) if agent_run_id else None,
                    "ok": result.ok,
                },
                db=db,
            )
        except Exception as exc:
            error = redact_text(str(exc))
            call.status = "failed"
            call.error = error
            call.completed_at = datetime.now(UTC)
            call.duration_ms = self._duration_ms(call.started_at, call.completed_at)
            db.add(
                AuditLog(
                    organization_id=organization_id,
                    actor_user_id=user_id,
                    action="tool.execute",
                    resource_type="tool_call",
                    resource_id=str(call.id),
                    status="failed",
                    metadata_json=redact_data({"tool": tool_name, "error": error}),
                )
            )
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.TOOL_CALL_FAILED,
                severity="error",
                payload={"id": str(call.id), "tool": tool_name, "error": error},
            )
            return ToolExecutionOutcome(status="failed", tool_call=call, error=error)

        if not result.ok:
            error = redact_text(result.error.message if result.error else "Tool returned a failed result.")
            call.status = "failed"
            call.error = error
            call.output_json = redact_data(result.model_dump(mode="json"))
            call.completed_at = datetime.now(UTC)
            call.duration_ms = self._duration_ms(call.started_at, call.completed_at)
            db.add(
                AuditLog(
                    organization_id=organization_id,
                    actor_user_id=user_id,
                    action="tool.execute",
                    resource_type="tool_call",
                    resource_id=str(call.id),
                    status="failed",
                    metadata_json=redact_data({"tool": tool_name, "error": error}),
                )
            )
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                agent_run_id=agent_run_id,
                tool_call_id=call.id,
                event_type=EventType.TOOL_CALL_FAILED,
                severity="warning",
                payload={"id": str(call.id), "tool": tool_name, "error": error, "result": call.output_json},
            )
            return ToolExecutionOutcome(status="failed", tool_call=call, output=call.output_json, error=error)

        await self._apply_success_side_effects(db, tool_name=tool_name, session_id=session_id, result=result)
        payload = redact_data(result.model_dump(mode="json"))
        call.status = "completed"
        call.output_json = payload
        call.completed_at = datetime.now(UTC)
        call.duration_ms = self._duration_ms(call.started_at, call.completed_at)
        db.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=user_id,
                action="tool.execute",
                resource_type="tool_call",
                resource_id=str(call.id),
                status="completed",
                metadata_json=redact_data({"tool": tool_name, "title": result.title}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=call.id,
            event_type=EventType.TOOL_CALL_COMPLETED,
            payload={"id": str(call.id), "tool": tool_name, "result": payload},
        )
        return ToolExecutionOutcome(status="completed", tool_call=call, output=payload)

    async def execute_approved_call(
        self,
        db: AsyncSession,
        *,
        tool_call: ToolCall,
        user_id: UUID | None,
        agent: AgentDefinition,
    ) -> ToolExecutionOutcome:
        tool_name = tool_call.tool_name
        try:
            tool = tool_registry.get(tool_name)
        except Exception as exc:
            return await self._fail_existing_call(
                db,
                tool_call=tool_call,
                user_id=user_id,
                error=redact_text(str(exc)),
                severity="error",
            )
        if tool_name not in agent.allowed_tools:
            return await self._fail_existing_call(
                db,
                tool_call=tool_call,
                user_id=user_id,
                error=redact_text(f"Tool {tool_name} is not allowed for agent {agent.id}."),
                severity="warning",
            )
        try:
            typed_input = tool.input_model.model_validate(tool_call.input_json)
        except ValidationError as exc:
            return await self._fail_existing_call(
                db,
                tool_call=tool_call,
                user_id=user_id,
                error=redact_text(f"Invalid approved tool input: {exc}"),
                severity="error",
            )

        tool_call.status = "running"
        tool_call.started_at = datetime.now(UTC)
        await event_bus.publish(
            db,
            organization_id=tool_call.organization_id,
            project_id=tool_call.project_id,
            workspace_id=tool_call.workspace_id,
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            event_type=EventType.TOOL_CALL_STARTED,
            payload={"id": str(tool_call.id), "tool": tool_name, "input": tool_call.input_json, "resumed": True},
        )
        ctx = ToolContext(
            organization_id=tool_call.organization_id,
            project_id=tool_call.project_id,
            workspace_id=tool_call.workspace_id,
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            agent_id=agent.id,
            workspace_root=get_settings().workspace_root,
            db=db,
        )
        try:
            result = await tool.run_with_timeout(typed_input, ctx)
        except Exception as exc:
            return await self._fail_existing_call(
                db,
                tool_call=tool_call,
                user_id=user_id,
                error=redact_text(str(exc)),
                severity="error",
            )

        if not result.ok:
            return await self._fail_existing_call(
                db,
                tool_call=tool_call,
                user_id=user_id,
                error=redact_text(result.error.message if result.error else "Tool returned a failed result."),
                severity="warning",
                output_json=redact_data(result.model_dump(mode="json")),
            )

        await self._apply_success_side_effects(db, tool_name=tool_name, session_id=tool_call.session_id, result=result)
        payload = redact_data(result.model_dump(mode="json"))
        tool_call.status = "completed"
        tool_call.output_json = payload
        tool_call.completed_at = datetime.now(UTC)
        tool_call.duration_ms = self._duration_ms(tool_call.started_at, tool_call.completed_at)
        db.add(
            AuditLog(
                organization_id=tool_call.organization_id,
                actor_user_id=user_id,
                action="tool.execute",
                resource_type="tool_call",
                resource_id=str(tool_call.id),
                status="completed",
                metadata_json=redact_data({"tool": tool_name, "title": result.title, "resumed": True}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=tool_call.organization_id,
            project_id=tool_call.project_id,
            workspace_id=tool_call.workspace_id,
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            event_type=EventType.TOOL_CALL_COMPLETED,
            payload={"id": str(tool_call.id), "tool": tool_name, "result": payload, "resumed": True},
        )
        return ToolExecutionOutcome(status="completed", tool_call=tool_call, output=payload)

    async def _fail_existing_call(
        self,
        db: AsyncSession,
        *,
        tool_call: ToolCall,
        user_id: UUID | None,
        error: str,
        severity: str,
        output_json: dict[str, Any] | None = None,
    ) -> ToolExecutionOutcome:
        tool_call.status = "failed"
        error = redact_text(error)
        tool_call.error = error
        if output_json is not None:
            tool_call.output_json = output_json
        tool_call.completed_at = datetime.now(UTC)
        tool_call.duration_ms = self._duration_ms(tool_call.started_at, tool_call.completed_at)
        db.add(
            AuditLog(
                organization_id=tool_call.organization_id,
                actor_user_id=user_id,
                action="tool.execute",
                resource_type="tool_call",
                resource_id=str(tool_call.id),
                status="failed",
                metadata_json=redact_data({"tool": tool_call.tool_name, "error": error, "resumed": True}),
            )
        )
        await event_bus.publish(
            db,
            organization_id=tool_call.organization_id,
            project_id=tool_call.project_id,
            workspace_id=tool_call.workspace_id,
            session_id=tool_call.session_id,
            agent_run_id=tool_call.agent_run_id,
            tool_call_id=tool_call.id,
            event_type=EventType.TOOL_CALL_FAILED,
            severity=severity,
            payload={"id": str(tool_call.id), "tool": tool_call.tool_name, "error": error, "resumed": True},
        )
        return ToolExecutionOutcome(status="failed", tool_call=tool_call, error=error)

    async def _apply_success_side_effects(
        self,
        db: AsyncSession,
        *,
        tool_name: str,
        session_id: UUID,
        result,
    ) -> None:
        if tool_name == "todo.write":
            session = await db.get(Session, session_id)
            if not session:
                return
            existing = list((session.metadata_json or {}).get("todos", []))
            payload = result.metadata or {}
            mode = payload.get("mode", "replace")
            todos = list(payload.get("todos", []))
            if mode == "update":
                by_id = {item.get("id"): item for item in existing if item.get("id")}
                for item in todos:
                    by_id[item.get("id")] = item
                todos = list(by_id.values())
            session.metadata_json = {**(session.metadata_json or {}), "todos": todos}
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                event_type=EventType.TODO_UPDATED,
                payload={"todos": todos, "mode": mode},
            )
        if tool_name == "question.ask":
            session = await db.get(Session, session_id)
            await event_bus.publish(
                db,
                organization_id=session.organization_id if session else None,
                project_id=session.project_id if session else None,
                workspace_id=session.workspace_id if session else None,
                session_id=session_id,
                event_type=EventType.QUESTION_REQUESTED,
                payload={"questions": result.metadata.get("questions", []) if result.metadata else []},
            )

    def _duration_ms(self, started_at: datetime | None, completed_at: datetime | None) -> int | None:
        if not started_at or not completed_at:
            return None
        return max(int((completed_at - started_at).total_seconds() * 1000), 0)


tool_executor = ToolExecutor()
