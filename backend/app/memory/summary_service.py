from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import Message, Session, SessionSummary
from backend.app.runtime.event_bus import event_bus


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


@dataclass(slots=True)
class SummaryCreate:
    session: Session
    summary_type: str
    content: str
    run_id: UUID | None = None
    source_message_start_id: UUID | None = None
    source_message_end_id: UUID | None = None
    source_message_count: int = 0
    model: str | None = None
    metadata: dict[str, Any] | None = None
    supersede_active: bool = False


def serialize_summary(summary: SessionSummary) -> dict[str, Any]:
    return {
        "id": str(summary.id),
        "session_id": str(summary.session_id),
        "run_id": str(summary.run_id) if summary.run_id else None,
        "summary_type": summary.summary_type,
        "content": redact_text(summary.content),
        "source_message_start_id": str(summary.source_message_start_id) if summary.source_message_start_id else None,
        "source_message_end_id": str(summary.source_message_end_id) if summary.source_message_end_id else None,
        "source_message_count": summary.source_message_count,
        "token_estimate": summary.token_estimate,
        "char_count": summary.char_count,
        "model": summary.model,
        "status": summary.status,
        "metadata": redact_data(summary.metadata_json),
        "created_at": summary.created_at.isoformat(),
        "updated_at": summary.updated_at.isoformat(),
    }


class SummaryService:
    async def create_summary(self, db: AsyncSession, payload: SummaryCreate) -> SessionSummary:
        content = redact_text(payload.content.strip())
        if not content:
            raise ValueError("Summary content cannot be empty.")
        if payload.supersede_active:
            await self.supersede_active(db, session_id=payload.session.id, superseded_by=None)
        summary = SessionSummary(
            session_id=payload.session.id,
            run_id=payload.run_id,
            summary_type=payload.summary_type,
            content=content,
            source_message_start_id=payload.source_message_start_id,
            source_message_end_id=payload.source_message_end_id,
            source_message_count=payload.source_message_count,
            token_estimate=estimate_tokens(content),
            char_count=len(content),
            model=payload.model,
            status="active",
            metadata_json=redact_data(payload.metadata or {}),
        )
        db.add(summary)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=payload.session.organization_id,
            project_id=payload.session.project_id,
            workspace_id=payload.session.workspace_id,
            session_id=payload.session.id,
            agent_run_id=payload.run_id,
            event_type=EventType.SUMMARY_CREATED,
            payload={"summary": serialize_summary(summary)},
        )
        return summary

    async def create_from_messages(
        self,
        db: AsyncSession,
        *,
        session: Session,
        messages: list[Message],
        content: str,
        summary_type: str = "rolling",
        run_id: UUID | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        supersede_active: bool = False,
    ) -> SessionSummary:
        ordered = sorted(messages, key=lambda item: (item.created_at, item.id))
        return await self.create_summary(
            db,
            SummaryCreate(
                session=session,
                run_id=run_id,
                summary_type=summary_type,
                content=content,
                source_message_start_id=ordered[0].id if ordered else None,
                source_message_end_id=ordered[-1].id if ordered else None,
                source_message_count=len(ordered),
                model=model,
                metadata=metadata,
                supersede_active=supersede_active,
            ),
        )

    async def list_active(self, db: AsyncSession, *, session_id: UUID) -> list[SessionSummary]:
        if hasattr(db, "objects"):
            rows = [
                row
                for (model, _row_id), row in db.objects.items()
                if model is SessionSummary and row.session_id == session_id and row.status == "active"
            ]
            return sorted(rows, key=lambda item: (item.created_at, item.id))
        result = await db.scalars(
            select(SessionSummary)
            .where(SessionSummary.session_id == session_id, SessionSummary.status == "active")
            .order_by(SessionSummary.created_at.asc(), SessionSummary.id.asc())
        )
        return list(result.all())

    async def latest(self, db: AsyncSession, *, session_id: UUID) -> SessionSummary | None:
        rows = await self.list_active(db, session_id=session_id)
        return rows[-1] if rows else None

    async def supersede_active(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        superseded_by: UUID | None,
    ) -> list[SessionSummary]:
        rows = await self.list_active(db, session_id=session_id)
        for row in rows:
            row.status = "superseded"
            metadata = dict(row.metadata_json or {})
            if superseded_by:
                metadata["superseded_by"] = str(superseded_by)
            row.metadata_json = metadata
            await event_bus.publish(
                db,
                session_id=row.session_id,
                agent_run_id=row.run_id,
                event_type=EventType.SUMMARY_SUPERSEDED,
                payload={"summary_id": str(row.id), "superseded_by": str(superseded_by) if superseded_by else None},
            )
        return rows

    async def record_failed(
        self,
        db: AsyncSession,
        *,
        session: Session,
        summary_type: str,
        error: str,
        run_id: UUID | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionSummary:
        safe_error = redact_text(error)
        summary = SessionSummary(
            session_id=session.id,
            run_id=run_id,
            summary_type=summary_type,
            content=safe_error,
            source_message_count=0,
            token_estimate=estimate_tokens(safe_error),
            char_count=len(safe_error),
            model=model,
            status="failed",
            metadata_json=redact_data({"error": safe_error, **(metadata or {})}),
        )
        db.add(summary)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run_id,
            event_type=EventType.SUMMARY_FAILED,
            severity="error",
            payload={"summary": serialize_summary(summary), "error": safe_error},
        )
        return summary


summary_service = SummaryService()
