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
from backend.app.codeintel.lsp_registry import (
    all_server_ids,
    get_preset,
    get_preset_for_language,
    get_server_attribute,
)
from backend.app.codeintel.repository import codeintel_repository
from backend.app.core.config import get_settings
from backend.app.tools.base import is_inside

SOURCE_REAL_LSP = "real_lsp"
SOURCE_STATIC_FALLBACK = "static_fallback"

STATUS_DISABLED = "disabled"
STATUS_MISSING_COMMAND = "missing_command"
STATUS_FAILED = "failed"
STATUS_STATIC_FALLBACK = "static_fallback"
STATUS_REAL_LSP = "real_lsp"

PRIMARY_LANGUAGE_FOR_HEALTH = "python"


@dataclass
class LspServiceState:
    server_id: str
    language: str
    real_lsp_enabled: bool = False
    mode: str = STATUS_STATIC_FALLBACK
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
        self._states: dict[str, LspServiceState] = {}
        for server_id in all_server_ids():
            preset = get_preset(server_id)
            if preset is None:
                continue
            primary_language = preset.languages[0] if preset.languages else server_id
            self._states[server_id] = LspServiceState(server_id=server_id, language=primary_language)

    def _state_for(self, language: str) -> LspServiceState:
        preset = get_preset_for_language(language)
        if preset is not None:
            return self._states[preset.server_id]
        for _sid, state in self._states.items():
            if state.language == language:
                return state
        return self._states["python"]

    def _server_id_for(self, language: str) -> str:
        preset = get_preset_for_language(language)
        if preset is not None:
            return preset.server_id
        return language

    def _client_for(self, language: str) -> LspClient | None:
        return multi_lsp_client.get_client(language)

    def _lsp_enabled_for(self, language: str) -> bool:
        server_id = self._server_id_for(language)
        return bool(get_server_attribute(get_settings().lsp, server_id, "enabled"))

    def _command_for(self, language: str) -> str:
        server_id = self._server_id_for(language)
        value = get_server_attribute(get_settings().lsp, server_id, "command")
        return str(value) if value else ""

    async def health(self) -> dict[str, Any]:
        await self._probe_servers()
        settings = get_settings()
        primary = self._states["python"]
        result = {
            "status": "ok" if any(s.real_lsp_enabled for s in self._states.values()) else "degraded",
            "mode": primary.mode,
            "real_lsp_enabled": primary.real_lsp_enabled,
            "command": primary.command or settings.lsp.python_command,
            "last_error": primary.last_error,
            "last_error_type": primary.last_error_type,
            "started_at": primary.started_at.isoformat() if primary.started_at else None,
            "started": primary.started_at.isoformat() if primary.started_at else None,
            "request_count": primary.request_count,
            "failure_count": primary.failure_count,
            "reason": primary.last_error,
            "lsp_servers": {sid: self._status_for_state(state) for sid, state in self._states.items()},
        }
        for sid, state in self._states.items():
            if self._include_debug_details(state):
                client = self._client_for(state.language)
                if client is not None:
                    self._states[sid].last_error and result.setdefault("debug", {})
                    snapshot = client.debug_snapshot()
                    result["lsp_servers"][sid]["debug"] = snapshot
        return result

    async def _probe_servers(self) -> None:
        for _server_id, state in self._states.items():
            enabled = self._lsp_enabled_for(state.language)
            state.command = self._command_for(state.language)
            if not enabled:
                state.real_lsp_enabled = False
                state.mode = STATUS_STATIC_FALLBACK
                state.last_error = "Static database index fallback is active."
                state.last_error_type = None
                continue
            client = self._client_for(state.language)
            if client is None:
                state.real_lsp_enabled = False
                state.mode = STATUS_MISSING_COMMAND
                state.last_error = f"No client for language {state.language}."
                state.last_error_type = None
                continue
            if not state.command:
                state.real_lsp_enabled = False
                state.mode = STATUS_MISSING_COMMAND
                state.last_error = "LSP command not configured."
                state.last_error_type = None
                continue
            try:
                ws_root = self._workspace_root_for(state.language)
                await client.initialize(ws_root)
                state.real_lsp_enabled = True
                state.mode = STATUS_REAL_LSP
                state.last_error = None
                state.last_error_type = None
                if state.started_at is None:
                    state.started_at = datetime.now(UTC)
            except Exception as exc:
                state.real_lsp_enabled = False
                state.mode = STATUS_FAILED
                state.last_error = f"{exc}. Static fallback remains available."
                state.last_error_type = type(exc).__name__

    def status(self, language: str = PRIMARY_LANGUAGE_FOR_HEALTH) -> dict[str, Any]:
        return self._status_for(self._state_for(language).language)

    def _status_for_state(self, state: LspServiceState) -> dict[str, Any]:
        enabled = self._lsp_enabled_for(state.language)
        preset = get_preset(state.server_id)
        started_iso = state.started_at.isoformat() if state.started_at else None
        payload = {
            "server_id": state.server_id,
            "status": "ok" if state.real_lsp_enabled else "degraded",
            "mode": state.mode,
            "real_lsp_enabled": state.real_lsp_enabled,
            "command": state.command or self._command_for(state.language),
            "last_error": state.last_error,
            "last_error_type": state.last_error_type,
            "started_at": started_iso,
            "started": started_iso,
            "request_count": state.request_count,
            "failure_count": state.failure_count,
            "reason": state.last_error,
            "lsp_server": state.server_id if state.real_lsp_enabled else "none",
            "language": state.language,
            "lsp_language": lsp_language_id(state.language),
            "enabled": enabled,
            "install_hint_windows": preset.install_hint_windows if preset else None,
            "install_hint_linux_ci": preset.install_hint_linux_ci if preset else None,
        }
        return payload

    def _status_for(self, language: str) -> dict[str, Any]:
        state = self._state_for(language)
        return self._status_for_state(state)

    async def shutdown(self) -> dict[str, Any]:
        for state in self._states.values():
            client = self._client_for(state.language)
            if client is not None:
                await client.shutdown()
            state.real_lsp_enabled = False
            enabled = self._lsp_enabled_for(state.language)
            if enabled:
                state.mode = STATUS_FAILED
                state.last_error = "Real LSP client stopped. Static fallback remains available."
                state.last_error_type = "RuntimeError"
            else:
                state.mode = STATUS_STATIC_FALLBACK
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
        detected = language or (detect_language(file_path) or PRIMARY_LANGUAGE_FOR_HEALTH)
        self._sync_disabled_state(detected)
        if self._should_use_real_lsp(detected):
            client = self._client_for(detected)
            if client is not None:
                try:
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
                        lsp_server=self._server_id_for(detected),
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
        detected = detect_language(file or "") or PRIMARY_LANGUAGE_FOR_HEALTH
        self._sync_disabled_state(detected)
        if file and line is not None and self._should_use_real_lsp(detected):
            client = self._client_for(detected)
            if client is not None:
                try:
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
                            lsp_server=self._server_id_for(detected),
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
        detected = detect_language(file or "") or PRIMARY_LANGUAGE_FOR_HEALTH
        self._sync_disabled_state(detected)
        if file and line is not None and self._should_use_real_lsp(detected):
            client = self._client_for(detected)
            if client is not None:
                try:
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
                            lsp_server=self._server_id_for(detected),
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
        detected = detect_language(file_path or "") or PRIMARY_LANGUAGE_FOR_HEALTH
        self._sync_disabled_state(detected)
        if file_path and self._should_use_real_lsp(detected):
            client = self._client_for(detected)
            if client is not None:
                try:
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
                            lsp_server=self._server_id_for(detected),
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
        return self._lsp_enabled_for(language)

    def _sync_disabled_state(self, language: str) -> None:
        if self._lsp_enabled_for(language):
            return
        state = self._state_for(language)
        state.real_lsp_enabled = False
        state.mode = STATUS_STATIC_FALLBACK
        state.last_error = "Static database index fallback is active."

    def _fallback_reason(self, language: str) -> str | None:
        state = self._state_for(language)
        server_id = self._server_id_for(language)
        if not self._lsp_enabled_for(language):
            return f"{server_id}_lsp_disabled"
        if state.mode == STATUS_MISSING_COMMAND:
            return f"{server_id}_lsp_command_missing"
        return state.last_error

    def _record_success(self, language: str) -> None:
        state = self._state_for(language)
        state.request_count += 1
        state.real_lsp_enabled = True
        state.mode = STATUS_REAL_LSP
        state.last_error = None
        state.last_error_type = None
        if state.started_at is None:
            state.started_at = datetime.now(UTC)

    def _record_failure(self, language: str, exc: Exception) -> None:
        state = self._state_for(language)
        state.request_count += 1
        state.failure_count += 1
        state.real_lsp_enabled = False
        state.mode = STATUS_FAILED
        state.last_error = f"{exc}. Static fallback remains available."
        state.last_error_type = type(exc).__name__

    def _include_debug_details(self, state: LspServiceState) -> bool:
        debug_flag = os.getenv("AP_LSP_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
        ci_flag = os.getenv("CI", "").strip().lower() in {"1", "true", "yes", "on"}
        return debug_flag or ci_flag or state.mode == STATUS_FAILED

    def _workspace_root_for(self, language: str) -> Path:
        server_id = self._server_id_for(language)
        ws = get_server_attribute(get_settings().lsp, server_id, "workspace_root")
        if ws:
            return ws
        return get_settings().lsp.workspace_root

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
