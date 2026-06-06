from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.codeintel.lsp_client import lsp_client
from backend.app.codeintel.repository import codeintel_repository
from backend.app.core.config import get_settings
from backend.app.tools.base import is_inside

SOURCE_REAL_LSP = "real_lsp"
SOURCE_STATIC_FALLBACK = "static_fallback"


@dataclass
class LspServiceState:
    real_lsp_enabled: bool = False
    mode: str = "static_fallback"
    command: str | None = None
    last_error: str | None = None
    started_at: datetime | None = None
    request_count: int = 0
    failure_count: int = 0


@dataclass
class LspResult:
    items: Any
    source: str
    lsp_status: str
    fallback_reason: str | None = None
    lsp: dict[str, Any] = field(default_factory=dict)


class LspService:
    def __init__(self) -> None:
        self._state = LspServiceState()

    async def health(self) -> dict[str, Any]:
        settings = get_settings()
        self._state.command = settings.lsp.python_command
        if not settings.lsp.enabled:
            self._state.real_lsp_enabled = False
            self._state.mode = "static_fallback"
            self._state.last_error = "Static database index fallback is active."
            return self.status()
        try:
            await lsp_client.initialize(settings.lsp.workspace_root)
        except Exception as exc:
            self._state.real_lsp_enabled = False
            self._state.mode = "failed"
            self._state.last_error = f"{exc}. Static fallback remains available."
            return self.status()
        self._state.real_lsp_enabled = True
        self._state.mode = "real_lsp"
        self._state.last_error = None
        if self._state.started_at is None:
            self._state.started_at = datetime.now(UTC)
        return self.status()

    def status(self) -> dict[str, Any]:
        started_iso = self._state.started_at.isoformat() if self._state.started_at else None
        return {
            "status": "ok" if self._state.real_lsp_enabled else "degraded",
            "mode": self._state.mode,
            "real_lsp_enabled": self._state.real_lsp_enabled,
            "command": self._state.command or get_settings().lsp.python_command,
            "last_error": self._state.last_error,
            "started_at": started_iso,
            "started": started_iso,
            "request_count": self._state.request_count,
            "failure_count": self._state.failure_count,
            "reason": self._state.last_error,
        }

    async def shutdown(self) -> dict[str, Any]:
        result = await lsp_client.shutdown()
        self._state.real_lsp_enabled = False
        if get_settings().lsp.enabled:
            self._state.mode = "failed"
            self._state.last_error = "Real LSP client stopped. Static fallback remains available."
        else:
            self._state.mode = "static_fallback"
            self._state.last_error = "Static database index fallback is active."
        return result

    async def document_symbols(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None,
        file_path: str,
        query: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        limit: int = 200,
    ) -> LspResult:
        self._sync_disabled_state()
        if self._should_use_real_lsp():
            try:
                symbols = await self._document_symbols_real(file_path)
                self._record_success()
                return LspResult(
                    items=self._filter_symbols(symbols, query=query, kind=kind, language=language, limit=limit),
                    source=SOURCE_REAL_LSP,
                    lsp_status=self._state.mode,
                    fallback_reason=None,
                    lsp=self.status(),
                )
            except Exception as exc:
                self._record_failure(exc)
        items = await codeintel_repository.find_symbols(
            db,
            workspace_id=workspace_id,
            query=query,
            file_path=file_path,
            kind=kind,
            language=language,
            limit=limit,
        )
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state.mode,
            fallback_reason=self._state.last_error,
            lsp=self.status(),
        )

    async def goto_definition(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None,
        name: str | None = None,
        file: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> LspResult:
        self._sync_disabled_state()
        if file and line is not None and self._should_use_real_lsp():
            try:
                location = await lsp_client.goto_definition(self._resolve_document_path(file), line, column or 0)
                self._record_success()
                normalized = self._normalize_definition(location)
                if normalized:
                    return LspResult(
                        items=normalized,
                        source=SOURCE_REAL_LSP,
                        lsp_status=self._state.mode,
                        fallback_reason=None,
                        lsp=self.status(),
                    )
            except Exception as exc:
                self._record_failure(exc)
        items = await self._fallback_definition(
            db,
            workspace_id=workspace_id,
            name=name,
            file=file,
            line=line,
        )
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state.mode,
            fallback_reason=self._state.last_error,
            lsp=self.status(),
        )

    async def find_references(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None,
        name: str | None = None,
        symbol_id: UUID | None = None,
        file: str | None = None,
        line: int | None = None,
        column: int | None = None,
        limit: int = 100,
    ) -> LspResult:
        self._sync_disabled_state()
        if file and line is not None and self._should_use_real_lsp():
            try:
                locations = await lsp_client.find_references(self._resolve_document_path(file), line, column or 0)
                self._record_success()
                normalized = self._normalize_references(locations)
                if normalized:
                    return LspResult(
                        items=normalized[:limit],
                        source=SOURCE_REAL_LSP,
                        lsp_status=self._state.mode,
                        fallback_reason=None,
                        lsp=self.status(),
                    )
            except Exception as exc:
                self._record_failure(exc)
        items = await codeintel_repository.find_references(
            db,
            workspace_id=workspace_id,
            name=name,
            symbol_id=symbol_id,
            limit=limit,
        )
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state.mode,
            fallback_reason=self._state.last_error,
            lsp=self.status(),
        )

    async def get_diagnostics(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None,
        file_path: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> LspResult:
        self._sync_disabled_state()
        if file_path and self._should_use_real_lsp():
            try:
                diagnostics = await lsp_client.diagnostics(self._resolve_document_path(file_path))
                self._record_success()
                normalized = self._normalize_diagnostics(diagnostics, file_path=file_path)
                if normalized:
                    return LspResult(
                        items=self._filter_diagnostics(normalized, severity=severity, limit=limit),
                        source=SOURCE_REAL_LSP,
                        lsp_status=self._state.mode,
                        fallback_reason=None,
                        lsp=self.status(),
                    )
            except Exception as exc:
                self._record_failure(exc)
        items = await codeintel_repository.list_diagnostics(
            db,
            workspace_id=workspace_id,
            file_path=file_path,
            severity=severity,
            limit=limit,
        )
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state.mode,
            fallback_reason=self._state.last_error,
            lsp=self.status(),
        )

    def _should_use_real_lsp(self) -> bool:
        settings = get_settings()
        self._state.command = settings.lsp.python_command
        return settings.lsp.enabled

    def _sync_disabled_state(self) -> None:
        if get_settings().lsp.enabled:
            return
        self._state.real_lsp_enabled = False
        self._state.mode = "static_fallback"
        self._state.last_error = "Static database index fallback is active."

    async def _document_symbols_real(self, file_path: str) -> list[dict[str, Any]]:
        raw_symbols = await lsp_client.document_symbols(self._resolve_document_path(file_path))
        return self._normalize_document_symbols(raw_symbols, file_path=file_path)

    async def _fallback_definition(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None,
        name: str | None,
        file: str | None,
        line: int | None,
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
        return None

    def _record_success(self) -> None:
        self._state.request_count += 1
        self._state.real_lsp_enabled = True
        self._state.mode = "real_lsp"
        self._state.last_error = None
        if self._state.started_at is None:
            self._state.started_at = datetime.now(UTC)

    def _record_failure(self, exc: Exception) -> None:
        self._state.request_count += 1
        self._state.failure_count += 1
        self._state.real_lsp_enabled = False
        self._state.mode = "failed"
        self._state.last_error = f"{exc}. Static fallback remains available."

    def _resolve_document_path(self, file_path: str) -> Path:
        workspace_root = get_settings().lsp.workspace_root.resolve()
        candidate = Path(file_path)
        resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
        if not is_inside(workspace_root, resolved):
            raise PermissionError(f"LSP document path is outside workspace root: {resolved}")
        return resolved

    def _normalize_document_symbols(self, payload: list[dict[str, Any]], *, file_path: str) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in payload:
            if "location" in item:
                name = item.get("name")
                location = item.get("location") or {}
                range_data = (location.get("range") or {}).get("start") or {}
                normalized.append(
                    {
                        "id": f"{file_path}:{name}:{range_data.get('line', 0)}",
                        "code_file_id": None,
                        "file_path": file_path,
                        "name": name,
                        "kind": str(item.get("kind")),
                        "language": None,
                        "start_line": int(range_data.get("line", 0)) + 1,
                        "end_line": int(((location.get("range") or {}).get("end") or {}).get("line", range_data.get("line", 0))) + 1,
                        "signature": None,
                        "docstring": None,
                        "parent_symbol_id": None,
                        "metadata": {"source": "lsp"},
                    }
                )
                continue
            symbol_range = (item.get("range") or {}).get("start") or {}
            normalized.append(
                {
                    "id": f"{file_path}:{item.get('name')}:{symbol_range.get('line', 0)}",
                    "code_file_id": None,
                    "file_path": file_path,
                    "name": item.get("name"),
                    "kind": str(item.get("kind")),
                    "language": None,
                    "start_line": int(symbol_range.get("line", 0)) + 1,
                    "end_line": int(((item.get("range") or {}).get("end") or {}).get("line", symbol_range.get("line", 0))) + 1,
                    "signature": None,
                    "docstring": None,
                    "parent_symbol_id": None,
                    "metadata": {"source": "lsp"},
                }
            )
        return normalized

    def _normalize_definition(self, payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict):
            return None
        uri = payload.get("uri") or (payload.get("targetUri") if isinstance(payload.get("targetUri"), str) else None)
        range_data = payload.get("range") or payload.get("targetSelectionRange") or {}
        start = range_data.get("start") or {}
        if not isinstance(uri, str):
            return None
        return {
            "id": f"{uri}:{start.get('line', 0)}",
            "name": self._path_from_uri(uri).stem,
            "kind": "definition",
            "file_path": self._workspace_relative_path(uri),
            "start_line": int(start.get("line", 0)) + 1,
            "end_line": int((range_data.get("end") or {}).get("line", start.get("line", 0))) + 1,
            "metadata": {"source": "lsp"},
        }

    def _normalize_references(self, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in payload:
            uri = item.get("uri")
            range_data = item.get("range") or {}
            start = range_data.get("start") or {}
            if not isinstance(uri, str):
                continue
            normalized.append(
                {
                    "id": f"{uri}:{start.get('line', 0)}:{start.get('character', 0)}",
                    "symbol_id": None,
                    "code_file_id": None,
                    "reference_name": self._path_from_uri(uri).stem,
                    "reference_type": "reference",
                    "line": int(start.get("line", 0)) + 1,
                    "column": int(start.get("character", 0)),
                    "snippet": None,
                    "file_path": self._workspace_relative_path(uri),
                    "metadata": {"source": "lsp"},
                }
            )
        return normalized

    def _normalize_diagnostics(self, payload: list[dict[str, Any]], *, file_path: str) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(payload):
            range_data = item.get("range") or {}
            start = range_data.get("start") or {}
            end = range_data.get("end") or {}
            normalized.append(
                {
                    "id": f"{file_path}:{index}:{start.get('line', 0)}",
                    "code_file_id": None,
                    "file_path": file_path,
                    "source": "lsp",
                    "severity": self._lsp_severity(item.get("severity")),
                    "code": item.get("code"),
                    "message": item.get("message"),
                    "line": int(start.get("line", 0)) + 1,
                    "column": int(start.get("character", 0)),
                    "end_line": int(end.get("line", start.get("line", 0))) + 1,
                    "end_column": int(end.get("character", start.get("character", 0))),
                    "metadata": {"source": "lsp"},
                    "created_at": None,
                }
            )
        return normalized

    def _filter_symbols(
        self,
        symbols: list[dict[str, Any]],
        *,
        query: str | None,
        kind: str | None,
        language: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = []
        for symbol in symbols:
            if query and query.lower() not in str(symbol.get("name", "")).lower():
                continue
            if kind and str(symbol.get("kind")) != kind:
                continue
            if language and str(symbol.get("language")) != language:
                continue
            rows.append(symbol)
        return rows[:limit]

    def _filter_diagnostics(
        self,
        diagnostics: list[dict[str, Any]],
        *,
        severity: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = diagnostics
        if severity:
            rows = [item for item in rows if item.get("severity") == severity]
        return rows[:limit]

    def _workspace_relative_path(self, uri: str) -> str:
        path = self._path_from_uri(uri)
        workspace_root = get_settings().lsp.workspace_root.resolve()
        try:
            return str(path.resolve().relative_to(workspace_root)).replace("\\", "/")
        except Exception:
            return path.name

    def _path_from_uri(self, uri: str) -> Path:
        path = unquote(urlparse(uri).path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)

    def _lsp_severity(self, severity: Any) -> str:
        mapping = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        return mapping.get(severity, "info")


lsp_service = LspService()
