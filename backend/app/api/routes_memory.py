from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.errors import NotFoundError
from backend.app.core.events import EventType
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.postgres import get_session
from backend.app.memory.memory_service import MemoryCreate, memory_service, serialize_memory_item
from backend.app.memory.summary_service import serialize_summary, summary_service
from backend.app.queue.jobs import runtime_queue, serialize_job
from backend.app.runtime.agent_runner import agent_runner
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.message_service import message_service
from backend.app.runtime.session_service import session_service
from backend.app.runtime.tenant import ensure_runtime_tenant

router = APIRouter(tags=["memory"])


class SummaryCreateRequest(BaseModel):
    content: str | None = None
    summary_type: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCreateRequest(BaseModel):
    content: str
    source_type: str = "project_note"
    source_id: str | None = None
    session_id: UUID | None = None
    visibility: str = "private"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompactionSeedRequest(BaseModel):
    session_id: UUID
    message: str = "Seed message for compaction smoke."
    summary_content: str = "Compaction smoke summary."


@router.get("/sessions/{session_id}/summaries")
async def list_session_summaries(
    session_id: UUID,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    session = await session_service.get(db, session_id, tenant_ctx=tenant)
    rows = await summary_service.list_active(db, session_id=session.id)
    return {"summaries": [serialize_summary(row) for row in rows]}


@router.post("/sessions/{session_id}/summaries")
async def create_session_summary(
    session_id: UUID,
    payload: SummaryCreateRequest,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    session = await session_service.get(db, session_id, tenant_ctx=tenant)
    summary = await agent_runner.create_session_summary(
        db,
        session=session,
        summary_type=payload.summary_type,
        content=payload.content,
        metadata=payload.metadata,
    )
    await db.commit()
    return {"summary": serialize_summary(summary)}


@router.get("/memory/items")
async def list_memory_items(
    session_id: UUID | None = None,
    query: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    rows = await memory_service.retrieve(
        db,
        organization_id=runtime_tenant.organization_id,
        project_id=runtime_tenant.project_id,
        workspace_id=runtime_tenant.workspace_id,
        session_id=session_id,
        query=query,
    )
    if status:
        rows = [row for row in rows if row.status == status]
    return {"memory_items": [serialize_memory_item(row) for row in rows]}


@router.post("/memory/items")
async def create_memory_item(
    payload: MemoryCreateRequest,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    item, created = await memory_service.create_item(
        db,
        MemoryCreate(
            organization_id=runtime_tenant.organization_id,
            project_id=runtime_tenant.project_id,
            workspace_id=runtime_tenant.workspace_id,
            session_id=payload.session_id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            content=payload.content,
            visibility=payload.visibility,
            metadata=payload.metadata,
        ),
    )
    await db.commit()
    return {"memory_item": serialize_memory_item(item), "created": created}


@router.get("/sessions/{session_id}/memory")
async def list_session_memory(
    session_id: UUID,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    session = await session_service.get(db, session_id, tenant_ctx=tenant)
    rows = await memory_service.retrieve(
        db,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
    )
    return {"memory_items": [serialize_memory_item(row) for row in rows]}


@router.post("/memory/test/compaction-seed")
async def seed_compaction_job(
    payload: CompactionSeedRequest,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.app.enable_test_endpoints or settings.app.env.lower() == "production":
        raise NotFoundError("Memory compaction test endpoint is disabled.")
    session = await session_service.get(db, payload.session_id, tenant_ctx=tenant)
    session.metadata_json = {
        **(session.metadata_json or {}),
        "test_compaction_content": payload.summary_content,
    }
    message = await message_service.create_assistant(
        db,
        session=session,
        content=payload.message,
        metadata={"test": True, "kind": "compaction_seed"},
    )
    if not settings.queue.enabled:
        raise RuntimeError("Compaction smoke requires AP_QUEUE_ENABLED=true.")
    job = await runtime_queue.enqueue_session_compaction(
        db,
        session_id=session.id,
        source_message_end_id=message.id,
        user_id=session.created_by_user_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        reason="test_seed",
        publish=False,
    )
    await event_bus.publish(
        db,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        event_type=EventType.COMPACTION_QUEUED,
        payload={"queue_job_id": str(job.id), "source_message_end_id": str(message.id), "test": True},
    )
    await db.commit()
    await runtime_queue.publish_job(job)
    return {"queue_job": serialize_job(job), "message_id": str(message.id)}
