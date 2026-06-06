from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.codeintel.language import detect_language, lsp_language_id
from backend.app.codeintel.lsp_client import LspClient, multi_lsp_client
from backend.app.codeintel.repository import codeintel_repository
from backend.app.core.config import get_settings
from backend.app.tools.base import is_inside

SOURCE_REAL_LSP = "real_lsp"
SOURCE_STATIC_FALLBACK = "static_fallback"

TS_LANGUAGES = {"typescript", "typescriptreact", "javascript", "javascriptreact"}
PYTHON_LANGUAGES = {"python"}


@dataclass
class LspServiceState:
    real_lsp_enabled: bool = False
    mode: str = "static_fallback"
    command: str | None = None
    last_error: str | None = None
    last_error_type: str | None = None
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
    language: str | None = None
    lsp_language: str | None = None
    lsp_server: str = "none"


class LspService:
    def __init__(self) -> None:
        self._python_state = LspServiceState()
        self._ts_state = LspServiceState()

    def _state_for(self, language: str) -> LspServiceState:
        if language in TS_LANGUAGES:
            return self._ts_state
        return self._python_state

    def _client_for(self, language: str) -> LspClient:
        return multi_lsp_client.get_client(language)

    def _lsp_enabled_for(self, language: str) -> bool:
        settings = get_settings()
        if language in TS_LANGUAGES:
            return getattr(settings.lsp, "ts_enabled", False)
        return settings.lsp.enabled

    async def health(self) -> dict[str, Any]:
        settings = get_settings()
        py_health = await self._language_health("python")
        ts_health = await self._language_health("typescript")
        result = {
            "status": "ok" if (py_health.get("real_lsp_enabled") or ts_health.get("ts", {}).get("real_lsp_enabled")) else "degraded",
            "mode": py_health.get("mode", "static_fallback"),
            "real_lsp_enabled": py_health.get("real_lsp_enabled", False),
            "command": py_health.get("command", settings.lsp.python_command),
            "last_error": py_health.get("last_error"),
            "last_error_type": py_health.get("last_error_type"),
            "started_at": py_health.get("started_at"),
            "started": py_health.get("started_at"),
            "request_count": py_health.get("request_count", 0),
            "failure_count": py_health.get("failure_count", 0),
            "reason": py_health.get("reason"),
            "lsp_servers": {
                "python": py_health,
                "typescript": ts_health.get("ts"),
            },
        }
        if "debug" in py_health:
            result["debug"] = py_health["debug"]
        return result

    async def _language_health(self, language: str) -> dict[str, Any]:
        settings = get_settings()
        state = self._state_for(language)
        client = self._client_for(language)
        enabled = self._lsp_enabled_for(language)

        if language == "python":
            state.command = settings.lsp.python_command
        else:
            state.command = getattr(settings.lsp, "ts_command", "")

        if not enabled:
            state.real_lsp_enabled = False
            state.mode = "static_fallback"
            state.last_error = "Static database index fallback is active."
            state.last_error_type = None
            result = self._status_for(language)
            if language != "python":
                return {"ts": result}
            return result

        try:
            ws_root = self._workspace_root_for(language)
            await client.initialize(ws_root)
        except Exception as exc:
            state.real_lsp_enabled = False
            state.mode = "failed"
            state.last_error = f"{exc}. Static fallback remains available."
            state.last_error_type = type(exc).__name__
            result = self._status_for(language)
            if language != "python":
                return {"ts": result}
            return result

        state.real_lsp_enabled = True
        state.mode = "real_lsp"
        state.last_error = None
        state.last_error_type = None
        if state.started_at is None:
            state.started_at = datetime.now(UTC)
        result = self._status_for(language)
        if language != "python":
            return {"ts": result}
        return result

    def status(self, language: str = "python") -> dict[str, Any]:
        return self._status_for(language)

    def _status_for(self, language: str) -> dict[str, Any]:
        state = self._state_for(language)
        client = self._client_for(language)
        started_iso = state.started_at.isoformat() if state.started_at else None
        enabled = self._lsp_enabled_for(language)
        settings = get_settings()
        cmd = settings.lsp.python_command if language == "python" else getattr(settings.lsp, "ts_command", "")

        payload = {
            "status": "ok" if state.real_lsp_enabled else "degraded",
            "mode": state.mode,
            "real_lsp_enabled": state.real_lsp_enabled,
            "command": state.command or cmd,
            "last_error": state.last_error,
            "last_error_type": state.last_error_type,
            "started_at": started_iso,
            "started": started_iso,
            "request_count": state.request_count,
            "failure_count": state.failure_count,
            "reason": state.last_error,
            "lsp_server": language if state.real_lsp_enabled else "none",
            "language": language,
            "lsp_language": lsp_language_id(language),
            "enabled": enabled,
        }
        if self._include_debug_details(state):
            payload["debug"] = client.debug_snapshot()
        return payload

    async def shutdown(self) -> dict[str, Any]:
        settings = get_settings()
        for language in ("python", "typescript"):
            state = self._state_for(language)
            client = self._client_for(language)
            await client.shutdown()
            state.real_lsp_enabled = False
            enabled = settings.lsp.enabled if language == "python" else getattr(settings.lsp, "ts_enabled", False)
            if enabled:
                state.mode = "failed"
                state.last_error = "Real LSP client stopped. Static fallback remains available."
                state.last_error_type = "RuntimeError"
            else:
                state.mode = "static_fallback"
                state.last_error = "Static database index fallback is active."
                state.last_error_type = None
        return {"status": "stopped"}

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
        detected = language or (detect_language(file_path) or "python")
        self._sync_disabled_state(detected)
        if self._should_use_real_lsp(detected):
            try:
                client = self._client_for(detected)
                raw_symbols = await client.document_symbols(self._resolve_document_path(file_path, detected))
                symbols = self._normalize_document_symbols(raw_symbols, file_path=file_path)
                self._record_success(detected)
                return LspResult(
                    items=self._filter_symbols(symbols, query=query, kind=kind, language=language, limit=limit),
                    source=SOURCE_REAL_LSP,
                    lsp_status=self._state_for(detected).mode,
                    fallback_reason=None,
                    lsp=self._status_for(detected),
                    language=detected,
                    lsp_language=lsp_language_id(detected),
                    lsp_server=detected,
                )
            except Exception as exc:
                self._record_failure(detected, exc)
        items = await codeintel_repository.find_symbols(
            db,
            workspace_id=workspace_id,
            query=query,
            file_path=file_path,
            kind=kind,
            language=language,
            limit=limit,
        )
        fallback_reason = self._fallback_reason(detected)
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state_for(detected).mode,
            fallback_reason=fallback_reason,
            lsp=self._status_for(detected),
            language=detected,
            lsp_language=lsp_language_id(detected),
            lsp_server="none",
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
        detected = detect_language(file or "") or "python"
        self._sync_disabled_state(detected)
        if file and line is not None and self._should_use_real_lsp(detected):
            try:
                client = self._client_for(detected)
                location = await client.goto_definition(self._resolve_document_path(file, detected), line, column or 0)
                self._record_success(detected)
                normalized = self._normalize_definition(location)
                if normalized:
                    return LspResult(
                        items=normalized,
                        source=SOURCE_REAL_LSP,
                        lsp_status=self._state_for(detected).mode,
                        fallback_reason=None,
                        lsp=self._status_for(detected),
                        language=detected,
                        lsp_language=lsp_language_id(detected),
                        lsp_server=detected,
                    )
            except Exception as exc:
                self._record_failure(detected, exc)
        items = await self._fallback_definition(
            db,
            workspace_id=workspace_id,
            name=name,
            file=file,
            line=line,
        )
        fallback_reason = self._fallback_reason(detected)
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state_for(detected).mode,
            fallback_reason=fallback_reason,
            lsp=self._status_for(detected),
            language=detected,
            lsp_language=lsp_language_id(detected),
            lsp_server="none",
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
        detected = detect_language(file or "") or "python"
        self._sync_disabled_state(detected)
        if file and line is not None and self._should_use_real_lsp(detected):
            try:
                client = self._client_for(detected)
                locations = await client.find_references(self._resolve_document_path(file, detected), line, column or 0)
                self._record_success(detected)
                normalized = self._normalize_references(locations)
                if normalized:
                    return LspResult(
                        items=normalized[:limit],
                        source=SOURCE_REAL_LSP,
                        lsp_status=self._state_for(detected).mode,
                        fallback_reason=None,
                        lsp=self._status_for(detected),
                        language=detected,
                        lsp_language=lsp_language_id(detected),
                        lsp_server=detected,
                    )
            except Exception as exc:
                self._record_failure(detected, exc)
        items = await codeintel_repository.find_references(
            db,
            workspace_id=workspace_id,
            name=name,
            symbol_id=symbol_id,
            limit=limit,
        )
        fallback_reason = self._fallback_reason(detected)
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state_for(detected).mode,
            fallback_reason=fallback_reason,
            lsp=self._status_for(detected),
            language=detected,
            lsp_language=lsp_language_id(detected),
            lsp_server="none",
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
        detected = detect_language(file_path or "") or "python"
        self._sync_disabled_state(detected)
        if file_path and self._should_use_real_lsp(detected):
            try:
                client = self._client_for(detected)
                diagnostics = await client.diagnostics(self._resolve_document_path(file_path, detected))
                self._record_success(detected)
                normalized = self._normalize_diagnostics(diagnostics, file_path=file_path)
                if normalized:
                    return LspResult(
                        items=self._filter_diagnostics(normalized, severity=severity, limit=limit),
                        source=SOURCE_REAL_LSP,
                        lsp_status=self._state_for(detected).mode,
                        fallback_reason=None,
                        lsp=self._status_for(detected),
                        language=detected,
                        lsp_language=lsp_language_id(detected),
                        lsp_server=detected,
                    )
            except Exception as exc:
                self._record_failure(detected, exc)
        items = await codeintel_repository.list_diagnostics(
            db,
            workspace_id=workspace_id,
            file_path=file_path,
            severity=severity,
            limit=limit,
        )
        fallback_reason = self._fallback_reason(detected)
        return LspResult(
            items=items,
            source=SOURCE_STATIC_FALLBACK,
            lsp_status=self._state_for(detected).mode,
            fallback_reason=fallback_reason,
            lsp=self._status_for(detected),
            language=detected,
            lsp_language=lsp_language_id(detected),
            lsp_server="none",
        )

    def _should_use_real_lsp(self, language: str) -> bool:
        settings = get_settings()
        state = self._state_for(language)
        if language in TS_LANGUAGES:
            state.command = getattr(settings.lsp, "ts_command", "")
            return getattr(settings.lsp, "ts_enabled", False)
        state.command = settings.lsp.python_command
        return settings.lsp.enabled

    def _sync_disabled_state(self, language: str) -> None:
        if self._lsp_enabled_for(language):
            return
        state = self._state_for(language)
        state.real_lsp_enabled = False
        state.mode = "static_fallback"
        state.last_error = "Static database index fallback is active."

    def _fallback_reason(self, language: str) -> str | None:
        state = self._state_for(language)
        if not self._lsp_enabled_for(language):
            if language in TS_LANGUAGES:
                return "typescript_lsp_disabled"
            return "python_lsp_disabled"
        return state.last_error

    def _record_success(self, language: str) -> None:
        state = self._state_for(language)
        state.request_count += 1
        state.real_lsp_enabled = True
        state.mode = "real_lsp"
        state.last_error = None
        state.last_error_type = None
        if state.started_at is None:
            state.started_at = datetime.now(UTC)

    def _record_failure(self, language: str, exc: Exception) -> None:
        state = self._state_for(language)
        state.request_count += 1
        state.failure_count += 1
        state.real_lsp_enabled = False
        state.mode = "failed"
        state.last_error = f"{exc}. Static fallback remains available."
        state.last_error_type = type(exc).__name__

    def _include_debug_details(self, state: LspServiceState) -> bool:
        debug_flag = os.getenv("AP_LSP_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
        ci_flag = os.getenv("CI", "").strip().lower() in {"1", "true", "yes", "on"}
        return debug_flag or ci_flag or state.mode == "failed"

    def _workspace_root_for(self, language: str) -> Path:
        settings = get_settings()
        if language in TS_LANGUAGES:
            ts_root = settings.lsp.ts_workspace_root
            if ts_root:
                return ts_root
        return settings.lsp.workspace_root

    def _resolve_document_path(self, file_path: str, language: str) -> Path:
        workspace_root = self._workspace_root_for(language).resolve()
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


lsp_service = LspService()
