from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.errors import NotFoundError
from backend.app.core.events import EventType
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.models import AgentRun, ToolCall
from backend.app.db.postgres import get_session
from backend.app.queue.jobs import runtime_queue, serialize_job
from backend.app.runtime.agent_runner import agent_runner
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.human_input_service import (
    HumanInputRequestCreate,
    HumanInputResumeSecurityError,
    HumanInputStateError,
    HumanInputValidationError,
    human_input_service,
    serialize_human_input_request,
)
from backend.app.runtime.loop_guard import input_hash
from backend.app.runtime.session_service import session_service
from backend.app.runtime.tenant import ensure_runtime_tenant

router = APIRouter(prefix="/human-input", tags=["human-input"])


class HumanInputAnswer(BaseModel):
    answer: str


class HumanInputCancel(BaseModel):
    message: str | None = None


class HumanInputSeed(BaseModel):
    session_id: UUID
    question: str = "Continue?"
    choices: list[str] = ["yes", "no"]
    allow_free_text: bool = False


@router.get("/requests")
async def list_human_input_requests(
    session_id: UUID | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    rows = await human_input_service.list_requests(
        db,
        organization_id=tenant.organization_id,
        session_id=session_id,
        status=status,
    )
    await db.commit()
    return {"requests": [serialize_human_input_request(row) for row in rows]}


@router.post("/test/seed")
async def seed_human_input_request(
    payload: HumanInputSeed,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    settings = get_settings()
    if settings.app.env.lower() == "production" or not settings.app.enable_test_endpoints:
        raise NotFoundError("Human input test endpoint is disabled.")
    session = await session_service.get(db, payload.session_id, tenant_ctx=tenant_ctx)
    tool_input = {
        "question": payload.question,
        "choices": payload.choices,
        "allow_free_text": payload.allow_free_text,
    }
    digest = input_hash(tool_input)
    run = AgentRun(
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_id=session.agent_id,
        model_provider=session.model_provider,
        model_name=session.model_name,
        status="waiting_human_input",
    )
    db.add(run)
    await db.flush()
    tool_call = ToolCall(
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=run.id,
        agent_id=session.agent_id,
        tool_name="question.ask",
        input_json=tool_input,
        input_hash=digest,
        status="waiting_human_input",
    )
    db.add(tool_call)
    await db.flush()
    request = await human_input_service.create_request(
        db,
        HumanInputRequestCreate(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            run_id=run.id,
            tool_call_id=tool_call.id,
            question=payload.question,
            details={"source": "test_seed"},
            request_hash=digest,
            metadata_json={
                "tool": "question.ask",
                "choices": payload.choices,
                "allow_free_text": payload.allow_free_text,
                "input_hash": digest,
                "test_complete_on_answer": True,
            },
        ),
    )
    session.status = "waiting_human_input"
    await event_bus.publish(
        db,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=run.id,
        tool_call_id=tool_call.id,
        event_type=EventType.AGENT_RUN_WAITING_HUMAN_INPUT,
        payload={"id": str(run.id), "human_input_request_id": str(request.id), "test": True},
    )
    await db.commit()
    return {
        "request": serialize_human_input_request(request),
        "agent_run": {"id": str(run.id), "status": run.status, "error": run.error, "step_count": run.step_count},
    }


@router.post("/{request_id}/answer")
async def answer_human_input(
    request_id: UUID,
    payload: HumanInputAnswer,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    try:
        context = await human_input_service.answer(
            db,
            request_id=request_id,
            answer=payload.answer,
            user_id=tenant.user_id,
        )
        if context.request.organization_id != tenant.organization_id:
            raise NotFoundError(f"Human input request not found: {request_id}")
        if get_settings().queue.enabled:
            context.run.status = "resume_queued"
            context.session.status = "resume_queued"
            await event_bus.publish(
                db,
                organization_id=context.request.organization_id,
                project_id=context.request.project_id,
                workspace_id=context.request.workspace_id,
                session_id=context.request.session_id,
                agent_run_id=context.request.run_id,
                tool_call_id=context.request.tool_call_id,
                event_type=EventType.AGENT_RUN_RESUME_QUEUED,
                payload={"id": str(context.run.id), "human_input_request_id": str(context.request.id)},
            )
            job = await runtime_queue.enqueue_human_input_resume(
                db,
                human_input_request_id=context.request.id,
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
                "request": serialize_human_input_request(context.request),
                "agent_run": {
                    "id": str(context.run.id),
                    "status": "resume_queued",
                    "error": context.run.error,
                    "step_count": context.run.step_count,
                },
                "queue_job": serialize_job(job),
            }
        run = await agent_runner.resume_after_human_input(db, context=context, user_id=tenant.user_id)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    except HumanInputStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HumanInputValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HumanInputResumeSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await db.commit()
    return {
        "request": serialize_human_input_request(context.request),
        "agent_run": {
            "id": str(run.id),
            "status": run.status,
            "error": run.error,
            "step_count": run.step_count,
        },
    }


@router.post("/{request_id}/cancel")
async def cancel_human_input(
    request_id: UUID,
    payload: HumanInputCancel | None = None,
    db: AsyncSession = Depends(get_session),
    tenant_ctx: TenantContext = Depends(tenant_context),
) -> dict:
    tenant = await ensure_runtime_tenant(db, tenant_ctx)
    try:
        context = await human_input_service.cancel(
            db,
            request_id=request_id,
            user_id=tenant.user_id,
            message=payload.message if payload else None,
        )
        if context.request.organization_id != tenant.organization_id:
            raise NotFoundError(f"Human input request not found: {request_id}")
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    except HumanInputStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HumanInputResumeSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await db.commit()
    return {
        "request": serialize_human_input_request(context.request),
        "agent_run": {
            "id": str(context.run.id),
            "status": context.run.status,
            "error": context.run.error,
            "step_count": context.run.step_count,
        },
    }
