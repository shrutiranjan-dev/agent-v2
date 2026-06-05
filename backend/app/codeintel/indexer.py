from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.codeintel.language import detect_language, is_supported_code_file
from backend.app.codeintel.parser import parse_code
from backend.app.codeintel.repository import codeintel_repository, serialize_code_file
from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data
from backend.app.memory.memory_service import MemoryCreate, memory_service
from backend.app.permissions.policy import secret_path_action
from backend.app.runtime.event_bus import event_bus
from backend.app.tools.base import (
    content_sha256,
    ensure_inside_workspace,
    is_inside,
    looks_binary,
    resolve_workspace_path,
)

DEFAULT_EXCLUDES = [
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "coverage",
    ".next",
    "external/opencode-source/.git",
]


class CodeIndexRequest(BaseModel):
    workspace_path: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    force: bool = False


@dataclass(slots=True)
class CodeIndexResult:
    files_indexed: int = 0
    files_skipped: int = 0
    files_ignored: int = 0
    files_deleted: int = 0
    symbols_found: int = 0
    references_found: int = 0
    diagnostics_found: int = 0
    duration_ms: int = 0
    code_map: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "files_indexed": self.files_indexed,
            "files_skipped": self.files_skipped,
            "files_ignored": self.files_ignored,
            "files_deleted": self.files_deleted,
            "symbols_found": self.symbols_found,
            "references_found": self.references_found,
            "diagnostics_found": self.diagnostics_found,
            "duration_ms": self.duration_ms,
            "code_map": self.code_map,
            "errors": self.errors,
        }


class WorkspaceIndexer:
    async def index_workspace(
        self,
        db: AsyncSession,
        *,
        workspace_root: Path,
        organization_id: UUID | None,
        project_id: UUID | None,
        workspace_id: UUID | None,
        request: CodeIndexRequest | None = None,
    ) -> CodeIndexResult:
        started = time.perf_counter()
        request = request or CodeIndexRequest()
        root = resolve_workspace_path(workspace_root, request.workspace_path or ".")
        ensure_inside_workspace(workspace_root, root, action="index")
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Workspace index root does not exist or is not a directory: {root}")

        await event_bus.publish(
            db,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            event_type=EventType.CODE_INDEX_STARTED,
            payload={"root": str(root), "force": request.force},
        )
        result = CodeIndexResult()
        seen_paths: set[str] = set()
        max_files = get_settings().codeintel.max_files
        try:
            for path in self._iter_files(root, workspace_root, include=request.include, exclude=request.exclude):
                if result.files_indexed + result.files_skipped >= max_files:
                    result.files_ignored += 1
                    continue
                rel = path.relative_to(workspace_root).as_posix()
                seen_paths.add(rel)
                indexed = await self._index_file(
                    db,
                    workspace_root=workspace_root,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    path=path,
                    relative_path=rel,
                    force=request.force,
                )
                if indexed is None:
                    result.files_skipped += 1
                    continue
                code_file, symbols, references = indexed
                result.files_indexed += 1
                result.symbols_found += len(symbols)
                result.references_found += len(references)
                await event_bus.publish(
                    db,
                    organization_id=organization_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    event_type=EventType.CODE_INDEX_FILE_INDEXED,
                    payload={
                        "file": serialize_code_file(code_file),
                        "symbols": len(symbols),
                        "references": len(references),
                    },
                )
            result.files_deleted = await self._mark_deleted(db, workspace_id=workspace_id, seen_paths=seen_paths)
            result.code_map = await codeintel_repository.code_map(db, workspace_id=workspace_id)
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            await self._store_code_map_memory(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                project_id=project_id,
                code_map=result.code_map,
            )
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                event_type=EventType.CODE_INDEX_COMPLETED,
                payload=redact_data(result.as_dict()),
            )
            return result
        except Exception as exc:
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                event_type=EventType.CODE_INDEX_FAILED,
                severity="error",
                payload={"error": str(exc), **result.as_dict()},
            )
            raise

    def _iter_files(self, root: Path, workspace_root: Path, *, include: list[str], exclude: list[str]):
        excludes = [*DEFAULT_EXCLUDES, *exclude]
        for path in root.rglob("*"):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not is_inside(workspace_root, resolved):
                continue
            rel = path.relative_to(workspace_root).as_posix()
            if self._excluded(rel, path, excludes):
                continue
            if path.is_dir():
                continue
            if include and not any(fnmatch.fnmatch(rel, pattern) for pattern in include):
                continue
            if not is_supported_code_file(path):
                continue
            if secret_path_action(path):
                continue
            yield path

    def _excluded(self, rel: str, path: Path, excludes: list[str]) -> bool:
        parts = set(path.parts)
        for pattern in excludes:
            normalized = pattern.strip("/")
            if not normalized:
                continue
            if normalized in parts:
                return True
            if fnmatch.fnmatch(rel, normalized) or fnmatch.fnmatch(rel, f"{normalized}/**"):
                return True
        return False

    async def _index_file(
        self,
        db: AsyncSession,
        *,
        workspace_root: Path,
        project_id: UUID | None,
        workspace_id: UUID | None,
        path: Path,
        relative_path: str,
        force: bool,
    ):
        settings = get_settings()
        data = path.read_bytes()
        if len(data) > settings.codeintel.max_file_bytes or looks_binary(data[: min(len(data), 8192)]):
            await codeintel_repository.upsert_file(
                db,
                project_id=project_id,
                workspace_id=workspace_id,
                path=relative_path,
                resolved_path=str(path.resolve()),
                language=detect_language(path),
                size_bytes=len(data),
                sha256=content_sha256(data),
                line_count=None,
                status="ignored",
                metadata={"reason": "binary_or_too_large"},
            )
            return None
        digest = content_sha256(data)
        existing = await codeintel_repository.get_file_by_path(db, workspace_id=workspace_id, path=relative_path)
        if existing and existing.sha256 == digest and existing.status == "active" and not force:
            return None
        text = data.decode("utf-8", errors="replace")
        language = detect_language(path)
        code_file, _changed = await codeintel_repository.upsert_file(
            db,
            project_id=project_id,
            workspace_id=workspace_id,
            path=relative_path,
            resolved_path=str(path.resolve()),
            language=language,
            size_bytes=len(data),
            sha256=digest,
            line_count=len(text.splitlines()),
            status="active",
            metadata={},
        )
        parsed = parse_code(path, text, language)
        symbols = [
            {
                "name": item.name,
                "kind": item.kind,
                "language": item.language,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "signature": item.signature,
                "docstring": item.docstring,
                "parent_name": item.parent_name,
                "metadata": item.metadata,
            }
            for item in parsed.symbols
        ]
        references = [
            {
                "reference_name": item.reference_name,
                "reference_type": item.reference_type,
                "line": item.line,
                "column": item.column,
                "snippet": item.snippet,
                "metadata": item.metadata,
            }
            for item in parsed.references
        ]
        created_symbols, created_refs = await codeintel_repository.replace_symbols_and_references(
            db,
            code_file=code_file,
            symbols=symbols,
            references=references,
        )
        return code_file, created_symbols, created_refs

    async def _mark_deleted(self, db: AsyncSession, *, workspace_id: UUID | None, seen_paths: set[str]) -> int:
        rows = await codeintel_repository.list_files(db, workspace_id=workspace_id, status="active", limit=10_000)
        deleted = 0
        for row in rows:
            if row.path in seen_paths:
                continue
            row.status = "deleted"
            deleted += 1
        return deleted

    async def _store_code_map_memory(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID | None,
        workspace_id: UUID | None,
        project_id: UUID | None,
        code_map: dict[str, Any],
    ) -> None:
        if not code_map.get("file_count"):
            return
        content = (
            "Code map summary: "
            f"{code_map.get('file_count', 0)} files, "
            f"{code_map.get('symbol_count', 0)} symbols, "
            f"languages={code_map.get('languages', {})}."
        )
        await memory_service.create_item(
            db,
            MemoryCreate(
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                source_type="code_note",
                source_id="code_map",
                content=content,
                visibility="workspace",
                metadata={"code_map": code_map},
            ),
        )


workspace_indexer = WorkspaceIndexer()
