from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.postgres import get_session
from backend.app.queue.jobs import runtime_queue, serialize_job
from backend.app.runtime.agent_runner import agent_runner
from backend.app.runtime.session_service import (
    UserMessageCreate,
    serialize_session,
    session_service,
)

router = APIRouter(prefix="/sessions", tags=["messages"])


@router.post("/{session_id}/messages")
async def create_message(
    session_id: UUID,
    payload: UserMessageCreate,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict:
    session = await session_service.get(db, session_id, tenant_ctx=tenant)
    message = await session_service.add_user_message(
        db,
        session=session,
        content=payload.content,
        agent_id=payload.agent_id,
        model_name=payload.model_name,
    )
    if get_settings().queue.enabled:
        run = await agent_runner.create_run(db, session=session, status="queued", user_message_id=message.id)
        job = await runtime_queue.enqueue_agent_run(
            db,
            agent_run_id=run.id,
            session_id=session.id,
            user_message_id=message.id,
            user_id=tenant.user_id,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            agent_id=session.agent_id,
            publish=False,
        )
        detail = await session_service.detail(db, session_id, tenant_ctx=tenant)
        await db.commit()
        await runtime_queue.publish_job(job)
        return {
            "session": serialize_session(session),
            "agent_run": {
                "id": str(run.id),
                "status": run.status,
                "error": run.error,
                "step_count": run.step_count,
            },
            "queue_job": serialize_job(job),
            **detail,
        }

    run = await agent_runner.run(db, session=session, user_id=tenant.user_id)
    detail = await session_service.detail(db, session_id, tenant_ctx=tenant)
    await db.commit()
    return {
        "session": serialize_session(session),
        "agent_run": {
            "id": str(run.id),
            "status": run.status,
            "error": run.error,
            "step_count": run.step_count,
        },
        **detail,
    }
