from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import MemoryItem, Session
from backend.app.providers.router import get_provider
from backend.app.runtime.event_bus import event_bus


@dataclass(slots=True)
class MemoryCreate:
    content: str
    source_type: str
    organization_id: UUID | None = None
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    session_id: UUID | None = None
    source_id: str | None = None
    visibility: str = "private"
    metadata: dict[str, Any] | None = None


def memory_content_hash(
    *,
    content: str,
    source_type: str,
    organization_id: UUID | None,
    project_id: UUID | None,
    workspace_id: UUID | None,
    session_id: UUID | None,
    visibility: str,
) -> str:
    scope = "|".join(
        [
            str(organization_id or ""),
            str(project_id or ""),
            str(workspace_id or ""),
            str(session_id or ""),
            visibility,
            source_type,
            content.strip(),
        ]
    )
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def serialize_memory_item(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "organization_id": str(item.organization_id) if item.organization_id else None,
        "project_id": str(item.project_id) if item.project_id else None,
        "workspace_id": str(item.workspace_id) if item.workspace_id else None,
        "session_id": str(item.session_id) if item.session_id else None,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "content": redact_text(item.content),
        "content_hash": item.content_hash,
        "embedding_model": item.embedding_model,
        "visibility": item.visibility,
        "status": item.status,
        "score": item.score,
        "metadata": redact_data(item.metadata_json),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


class MemoryService:
    async def create_item(self, db: AsyncSession, payload: MemoryCreate) -> tuple[MemoryItem, bool]:
        content = redact_text(payload.content.strip())
        if not content:
            raise ValueError("Memory content cannot be empty.")
        content_hash = memory_content_hash(
            content=content,
            source_type=payload.source_type,
            organization_id=payload.organization_id,
            project_id=payload.project_id,
            workspace_id=payload.workspace_id,
            session_id=payload.session_id,
            visibility=payload.visibility,
        )
        existing = await self.get_by_hash(db, content_hash)
        if existing:
            await event_bus.publish(
                db,
                organization_id=existing.organization_id,
                project_id=existing.project_id,
                workspace_id=existing.workspace_id,
                session_id=existing.session_id,
                event_type=EventType.MEMORY_ITEM_DEDUPED,
                payload={"memory_item_id": str(existing.id), "content_hash": content_hash},
            )
            return existing, False

        embedding, embedding_model, embedding_status = await self._maybe_embed(content)
        metadata = redact_data(payload.metadata or {})
        metadata["embedding_status"] = embedding_status
        if not hasattr(db, "objects"):
            stmt = (
                insert(MemoryItem)
                .values(
                    organization_id=payload.organization_id,
                    project_id=payload.project_id,
                    workspace_id=payload.workspace_id,
                    session_id=payload.session_id,
                    kind=payload.source_type,
                    source_type=payload.source_type,
                    source_id=payload.source_id,
                    content=content,
                    content_hash=content_hash,
                    embedding=embedding,
                    embedding_model=embedding_model,
                    visibility=payload.visibility,
                    status="active",
                    metadata_json=metadata,
                )
                .on_conflict_do_nothing(index_elements=["content_hash"])
                .returning(MemoryItem.id)
            )
            result = await db.execute(stmt)
            inserted_id = result.scalar_one_or_none()
            if not inserted_id:
                existing = await self.get_by_hash(db, content_hash)
                if existing:
                    return existing, False
                raise RuntimeError(f"Unable to create or load memory item for content hash {content_hash}")
            item = await db.get(MemoryItem, inserted_id)
            if item is None:
                raise RuntimeError(f"Unable to load created memory item {inserted_id}")
        else:
            item = MemoryItem(
                organization_id=payload.organization_id,
                project_id=payload.project_id,
                workspace_id=payload.workspace_id,
                session_id=payload.session_id,
                kind=payload.source_type,
                source_type=payload.source_type,
                source_id=payload.source_id,
                content=content,
                content_hash=content_hash,
                embedding=embedding,
                embedding_model=embedding_model,
                visibility=payload.visibility,
                status="active",
                metadata_json=metadata,
            )
            db.add(item)
            await db.flush()

        await event_bus.publish(
            db,
            organization_id=item.organization_id,
            project_id=item.project_id,
            workspace_id=item.workspace_id,
            session_id=item.session_id,
            event_type=EventType.MEMORY_ITEM_CREATED,
            payload={"memory_item": serialize_memory_item(item)},
        )
        return item, True

    async def create_from_session_summary(
        self,
        db: AsyncSession,
        *,
        session: Session,
        summary_id: UUID,
        content: str,
        visibility: str = "private",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[MemoryItem, bool]:
        return await self.create_item(
            db,
            MemoryCreate(
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                source_type="session_summary",
                source_id=str(summary_id),
                content=content,
                visibility=visibility,
                metadata=metadata,
            ),
        )

    async def get_by_hash(self, db: AsyncSession, content_hash: str) -> MemoryItem | None:
        if hasattr(db, "objects"):
            for (model, _row_id), row in db.objects.items():
                if model is MemoryItem and getattr(row, "content_hash", None) == content_hash:
                    return row
            return None
        return await db.scalar(select(MemoryItem).where(MemoryItem.content_hash == content_hash))

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        session_id: UUID | None = None,
        query: str | None = None,
        limit: int | None = None,
        visibility: list[str] | None = None,
    ) -> list[MemoryItem]:
        settings = get_settings()
        max_rows = limit or settings.memory.text_search_limit
        allowed_visibility = visibility or ["private", "project", "workspace", "organization"]
        if hasattr(db, "objects"):
            rows = [
                row
                for (model, _row_id), row in db.objects.items()
                if model is MemoryItem
                and row.status == "active"
                and row.visibility in allowed_visibility
                and self._scope_matches(
                    row,
                    organization_id=organization_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
                and self._query_matches(row, query)
            ]
            return sorted(rows, key=lambda item: (item.created_at, item.id), reverse=True)[:max_rows]

        conditions = [MemoryItem.status == "active", MemoryItem.visibility.in_(allowed_visibility)]
        if organization_id:
            conditions.append(or_(MemoryItem.organization_id == organization_id, MemoryItem.organization_id.is_(None)))
        if project_id:
            conditions.append(or_(MemoryItem.project_id == project_id, MemoryItem.project_id.is_(None)))
        if workspace_id:
            conditions.append(or_(MemoryItem.workspace_id == workspace_id, MemoryItem.workspace_id.is_(None)))
        if session_id:
            conditions.append(or_(MemoryItem.session_id == session_id, MemoryItem.session_id.is_(None)))
        if query:
            conditions.append(MemoryItem.content.ilike(f"%{query}%"))
        result = await db.scalars(
            select(MemoryItem).where(*conditions).order_by(MemoryItem.created_at.desc()).limit(max_rows)
        )
        return list(result.all())

    def _scope_matches(
        self,
        row: MemoryItem,
        *,
        organization_id: UUID | None,
        project_id: UUID | None,
        workspace_id: UUID | None,
        session_id: UUID | None,
    ) -> bool:
        return all(
            [
                row.organization_id in {None, organization_id},
                row.project_id in {None, project_id},
                row.workspace_id in {None, workspace_id},
                row.session_id in {None, session_id},
            ]
        )

    def _query_matches(self, row: MemoryItem, query: str | None) -> bool:
        return not query or query.lower() in row.content.lower()

    async def _maybe_embed(self, content: str) -> tuple[list[float] | None, str | None, str]:
        settings = get_settings()
        model = settings.memory.embedding_model
        if not settings.memory.embedding_enabled or not model:
            return None, model, "disabled"
        try:
            response = await get_provider("ollama").embed(model=model, input_text=content)
        except Exception as exc:
            return None, model, f"failed:{redact_text(str(exc))}"
        embedding = response.get("embedding")
        if not isinstance(embedding, list) or not all(isinstance(item, int | float) for item in embedding):
            return None, model, "failed:invalid_embedding_response"
        if len(embedding) != settings.memory.embedding_dimensions:
            return None, model, f"failed:dimension_mismatch:{len(embedding)}"
        return [float(item) for item in embedding], model, "stored"


memory_service = MemoryService()
