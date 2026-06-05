from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.codeintel.repository import codeintel_repository
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_text
from backend.app.db.models import CodeDiagnostic
from backend.app.runtime.event_bus import event_bus

RUFF_LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<column>\d+):\s+(?P<code>[A-Z]+\d+)\s+(?P<message>.+)$"
)


@dataclass(slots=True)
class DiagnosticInput:
    path: str
    source: str
    severity: str
    message: str
    line: int
    column: int | None = None
    code: str | None = None
    end_line: int | None = None
    end_column: int | None = None
    metadata: dict[str, Any] | None = None


def parse_ruff_output(output: str) -> list[DiagnosticInput]:
    diagnostics: list[DiagnosticInput] = []
    for line in output.splitlines():
        match = RUFF_LINE_RE.match(line.strip())
        if not match:
            continue
        diagnostics.append(
            DiagnosticInput(
                path=match.group("path"),
                source="ruff",
                severity="warning",
                code=match.group("code"),
                message=match.group("message"),
                line=int(match.group("line")),
                column=int(match.group("column")),
            )
        )
    return diagnostics


class DiagnosticsService:
    async def ingest(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None,
        diagnostics: list[DiagnosticInput],
    ) -> list[CodeDiagnostic]:
        rows: list[CodeDiagnostic] = []
        for item in diagnostics:
            code_file = await codeintel_repository.get_file_by_path(
                db,
                workspace_id=workspace_id,
                path=Path(item.path).as_posix(),
            )
            if not code_file:
                continue
            rows.append(
                await codeintel_repository.create_diagnostic(
                    db,
                    code_file=code_file,
                    source=item.source,
                    severity=item.severity,
                    code=item.code,
                    message=redact_text(item.message),
                    line=item.line,
                    column=item.column,
                    end_line=item.end_line,
                    end_column=item.end_column,
                    metadata=item.metadata,
                )
            )
        if rows:
            await event_bus.publish(
                db,
                workspace_id=workspace_id,
                event_type=EventType.CODE_DIAGNOSTICS_INGESTED,
                payload={"count": len(rows), "sources": sorted({row.source for row in rows})},
            )
        return rows

    async def degraded_status(self) -> dict[str, str]:
        return {"status": "degraded", "reason": "diagnostics ingestion is direct/static; no live LSP diagnostics configured"}


diagnostics_service = DiagnosticsService()
