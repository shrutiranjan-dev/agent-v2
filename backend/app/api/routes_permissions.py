from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.errors import NotFoundError
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.postgres import get_session
from backend.app.permissions.service import (
    PermissionResumeSecurityError,
    PermissionStateError,
    permission_service,
)
from backend.app.queue.jobs import runtime_queue, serialize_job
from backend.app.runtime.agent_runner import agent_runner
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.tenant import ensure_runtime_tenant

router = APIRouter(prefix="/permissions", tags=["permissions"])


class PermissionReply(BaseModel):
    message: str | None = None


def serialize_permission(row) -> dict:
    return {
        "id": str(row.id),
        "session_id": str(row.session_id),
        "agent_run_id": str(row.agent_run_id) if row.agent_run_id else None,
        "tool_call_id": str(row.tool_call_id) if row.tool_call_id else None,
        "permission_key": row.permission_key,
        "resource": row.resource,
        "status": row.status,
        "input": redact_data(row.input_json),
        "metadata": redact_data(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


@router.get("")
async def list_permissions(
    session_id: UUID | None = None,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    rows = await permission_service.list_pending(db, organization_id=tenant.organization_id, session_id=session_id)
    await db.commit()
    return {"permissions": [serialize_permission(row) for row in rows]}


@router.post("/{permission_id}/approve")
async def approve_permission(
    permission_id: UUID,
    payload: PermissionReply | None = None,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    try:
        context = await permission_service.approve(
            db,
            request_id=permission_id,
            user_id=tenant.user_id,
            message=payload.message if payload else None,
        )
        if get_settings().queue.enabled:
            context.run.status = "resume_queued"
            context.session.status = "resume_queued"
            await event_bus.publish(
                db,
                organization_id=context.request.organization_id,
                project_id=context.request.project_id,
                workspace_id=context.request.workspace_id,
                session_id=context.request.session_id,
                agent_run_id=context.request.agent_run_id,
                tool_call_id=context.request.tool_call_id,
                event_type=EventType.AGENT_RUN_RESUME_QUEUED,
                payload={"id": str(context.run.id), "permission_request_id": str(context.request.id)},
            )
            job = await runtime_queue.enqueue_permission_resume(
                db,
                permission_request_id=context.request.id,
                agent_run_id=context.run.id,
                session_id=context.session.id,
                user_id=tenant.user_id,
                organization_id=context.request.organization_id,
                project_id=context.request.project_id,
                workspace_id=context.request.workspace_id,
                publish=False,
            )
            await db.commit()
            await runtime_queue.publish_job(job)
            return {
                "permission": serialize_permission(context.request),
                "agent_run": {
                    "id": str(context.run.id),
                    "status": "resume_queued",
                    "error": context.run.error,
                    "step_count": context.run.step_count,
                },
                "queue_job": serialize_job(job),
            }
        run = await agent_runner.resume_after_permission(
            db,
            session=context.session,
            run=context.run,
            tool_call=context.tool_call,
            user_id=tenant.user_id,
        )
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    except PermissionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionResumeSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await db.commit()
    return {
        "permission": serialize_permission(context.request),
        "agent_run": {
            "id": str(run.id),
            "status": run.status,
            "error": run.error,
            "step_count": run.step_count,
        },
    }


@router.post("/{permission_id}/deny")
async def deny_permission(
    permission_id: UUID,
    payload: PermissionReply | None = None,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    try:
        context = await permission_service.deny(
            db,
            request_id=permission_id,
            user_id=tenant.user_id,
            message=payload.message if payload else None,
        )
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    except PermissionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionResumeSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await db.commit()
    return {
        "permission": serialize_permission(context.request),
        "agent_run": {
            "id": str(context.run.id),
            "status": context.run.status,
            "error": context.run.error,
            "step_count": context.run.step_count,
        },
    }
