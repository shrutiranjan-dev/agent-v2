from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.codeintel.repository import codeintel_repository
from backend.app.core.config import get_settings


class LspClient:
    """Honest LSP adapter.

    Batch 1 intentionally ships a DB-backed static fallback. Real language
    server processes remain disabled until configured and validated.
    """

    async def initialize(self) -> dict[str, Any]:
        return self.status()

    async def shutdown(self) -> dict[str, Any]:
        return {"status": "stopped", "mode": "static_fallback"}

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        if settings.codeintel.lsp_enabled:
            return {
                "status": "degraded",
                "mode": "static_fallback",
                "real_lsp_enabled": False,
                "reason": "Real LSP process management is not wired in this batch.",
            }
        return {
            "status": "degraded",
            "mode": "static_fallback",
            "real_lsp_enabled": False,
            "reason": "Static database index fallback is active.",
        }

    async def get_diagnostics(
        self,
        db: AsyncSession,
        *,
        workspace_id=None,
        file: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await codeintel_repository.list_diagnostics(
            db,
            workspace_id=workspace_id,
            file_path=file,
            severity=severity,
            limit=limit,
        )

    async def goto_definition(
        self,
        db: AsyncSession,
        *,
        workspace_id=None,
        name: str | None = None,
        file: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> dict[str, Any] | None:
        if name:
            symbols = await codeintel_repository.find_symbols(
                db,
                workspace_id=workspace_id,
                query=name,
                limit=10,
            )
            exact = [symbol for symbol in symbols if symbol["name"] == name]
            return (exact or symbols)[0] if symbols else None
        if file and line is not None:
            symbols = await codeintel_repository.find_symbols(
                db,
                workspace_id=workspace_id,
                file_path=file,
                limit=200,
            )
            containing = [
                symbol
                for symbol in symbols
                if symbol["start_line"] <= line <= (symbol.get("end_line") or symbol["start_line"])
            ]
            if containing:
                return sorted(containing, key=lambda item: item["start_line"], reverse=True)[0]
        _ = column
        return None

    async def find_references(
        self,
        db: AsyncSession,
        *,
        workspace_id=None,
        name: str | None = None,
        symbol_id=None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await codeintel_repository.find_references(
            db,
            workspace_id=workspace_id,
            name=name,
            symbol_id=symbol_id,
            limit=limit,
        )

    async def document_symbols(
        self,
        db: AsyncSession,
        *,
        workspace_id=None,
        file: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return await codeintel_repository.find_symbols(
            db,
            workspace_id=workspace_id,
            file_path=file,
            limit=limit,
        )


lsp_client = LspClient()
