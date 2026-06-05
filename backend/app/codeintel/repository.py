from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import CodeDiagnostic, CodeFile, CodeReference, CodeSymbol


def serialize_code_file(row: CodeFile) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id) if row.project_id else None,
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "path": row.path,
        "resolved_path": row.resolved_path,
        "language": row.language,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "line_count": row.line_count,
        "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
        "status": row.status,
        "metadata": redact_data(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_symbol(row: CodeSymbol, file: CodeFile | None = None) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "code_file_id": str(row.code_file_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "name": row.name,
        "kind": row.kind,
        "language": row.language,
        "start_line": row.start_line,
        "end_line": row.end_line,
        "signature": redact_text(row.signature) if row.signature else None,
        "docstring": redact_text(row.docstring) if row.docstring else None,
        "parent_symbol_id": str(row.parent_symbol_id) if row.parent_symbol_id else None,
        "metadata": redact_data(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
    if file:
        data["file"] = serialize_code_file(file)
        data["file_path"] = file.path
    return data


def serialize_reference(row: CodeReference, file: CodeFile | None = None) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "symbol_id": str(row.symbol_id) if row.symbol_id else None,
        "code_file_id": str(row.code_file_id),
        "reference_name": row.reference_name,
        "reference_type": row.reference_type,
        "line": row.line,
        "column": row.column,
        "snippet": redact_text(row.snippet) if row.snippet else None,
        "metadata": redact_data(row.metadata_json),
        "created_at": row.created_at.isoformat(),
    }
    if file:
        data["file"] = serialize_code_file(file)
        data["file_path"] = file.path
    return data


def serialize_diagnostic(row: CodeDiagnostic, file: CodeFile | None = None) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "code_file_id": str(row.code_file_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "source": row.source,
        "severity": row.severity,
        "code": row.code,
        "message": redact_text(row.message),
        "line": row.line,
        "column": row.column,
        "end_line": row.end_line,
        "end_column": row.end_column,
        "metadata": redact_data(row.metadata_json),
        "created_at": row.created_at.isoformat(),
    }
    if file:
        data["file"] = serialize_code_file(file)
        data["file_path"] = file.path
    return data


class CodeIntelRepository:
    async def get_file_by_path(self, db: AsyncSession, *, workspace_id: UUID | None, path: str) -> CodeFile | None:
        if hasattr(db, "objects"):
            for (model, _row_id), row in db.objects.items():
                if model is CodeFile and row.workspace_id == workspace_id and row.path == path:
                    return row
            return None
        return await db.scalar(select(CodeFile).where(CodeFile.workspace_id == workspace_id, CodeFile.path == path))

    async def upsert_file(
        self,
        db: AsyncSession,
        *,
        project_id: UUID | None,
        workspace_id: UUID | None,
        path: str,
        resolved_path: str,
        language: str | None,
        size_bytes: int,
        sha256: str,
        line_count: int | None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[CodeFile, bool]:
        existing = await self.get_file_by_path(db, workspace_id=workspace_id, path=path)
        now = datetime.now(UTC)
        if existing:
            changed = existing.sha256 != sha256 or existing.status != status
            existing.project_id = project_id
            existing.resolved_path = resolved_path
            existing.language = language
            existing.size_bytes = size_bytes
            existing.sha256 = sha256
            existing.line_count = line_count
            existing.indexed_at = now
            existing.status = status
            existing.metadata_json = redact_data(metadata or {})
            existing.updated_at = now
            await db.flush()
            return existing, changed
        if not hasattr(db, "objects"):
            stmt = (
                insert(CodeFile)
                .values(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    path=path,
                    resolved_path=resolved_path,
                    language=language,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    line_count=line_count,
                    indexed_at=now,
                    status=status,
                    metadata_json=redact_data(metadata or {}),
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_code_files_workspace_path",
                    set_={
                        "project_id": project_id,
                        "resolved_path": resolved_path,
                        "language": language,
                        "size_bytes": size_bytes,
                        "sha256": sha256,
                        "line_count": line_count,
                        "indexed_at": now,
                        "status": status,
                        "metadata_json": redact_data(metadata or {}),
                        "updated_at": now,
                    },
                )
                .returning(CodeFile.id)
            )
            row_id = (await db.execute(stmt)).scalar_one()
            row = await db.get(CodeFile, row_id)
            if row is None:
                raise RuntimeError(f"Unable to load indexed code file {path}")
            return row, True
        row = CodeFile(
            project_id=project_id,
            workspace_id=workspace_id,
            path=path,
            resolved_path=resolved_path,
            language=language,
            size_bytes=size_bytes,
            sha256=sha256,
            line_count=line_count,
            indexed_at=now,
            status=status,
            metadata_json=redact_data(metadata or {}),
        )
        db.add(row)
        await db.flush()
        return row, True

    async def replace_symbols_and_references(
        self,
        db: AsyncSession,
        *,
        code_file: CodeFile,
        symbols: list[dict[str, Any]],
        references: list[dict[str, Any]],
    ) -> tuple[list[CodeSymbol], list[CodeReference]]:
        if hasattr(db, "objects"):
            for key, row in list(db.objects.items()):
                if key[0] in {CodeSymbol, CodeReference} and getattr(row, "code_file_id", None) == code_file.id:
                    del db.objects[key]
            db.added = [
                row for row in db.added if not (isinstance(row, CodeSymbol | CodeReference) and row.code_file_id == code_file.id)
            ]
        else:
            await db.execute(delete(CodeReference).where(CodeReference.code_file_id == code_file.id))
            await db.execute(delete(CodeSymbol).where(CodeSymbol.code_file_id == code_file.id))

        created_symbols: list[CodeSymbol] = []
        parent_by_name: dict[str, CodeSymbol] = {}
        for item in symbols:
            parent = parent_by_name.get(str(item.get("parent_name") or ""))
            symbol = CodeSymbol(
                code_file_id=code_file.id,
                workspace_id=code_file.workspace_id,
                name=str(item["name"]),
                kind=str(item.get("kind") or "unknown"),
                language=item.get("language") or code_file.language,
                start_line=int(item.get("start_line") or 1),
                end_line=item.get("end_line"),
                signature=item.get("signature"),
                docstring=item.get("docstring"),
                parent_symbol_id=parent.id if parent else None,
                metadata_json=redact_data(item.get("metadata") or {}),
            )
            db.add(symbol)
            await db.flush()
            created_symbols.append(symbol)
            parent_by_name[symbol.name] = symbol

        symbol_by_name = {symbol.name: symbol for symbol in created_symbols}
        created_refs: list[CodeReference] = []
        for item in references:
            name = str(item["reference_name"])
            symbol = symbol_by_name.get(name)
            ref = CodeReference(
                symbol_id=symbol.id if symbol else None,
                code_file_id=code_file.id,
                reference_name=name,
                reference_type=str(item.get("reference_type") or "unknown"),
                line=int(item.get("line") or 1),
                column=item.get("column"),
                snippet=item.get("snippet"),
                metadata_json=redact_data(item.get("metadata") or {}),
            )
            db.add(ref)
            await db.flush()
            created_refs.append(ref)
        return created_symbols, created_refs

    async def list_files(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None = None,
        language: str | None = None,
        status: str | None = "active",
        limit: int = 500,
    ) -> list[CodeFile]:
        if hasattr(db, "objects"):
            rows = [row for (model, _), row in db.objects.items() if model is CodeFile]
            if workspace_id:
                rows = [row for row in rows if row.workspace_id == workspace_id]
            if language:
                rows = [row for row in rows if row.language == language]
            if status:
                rows = [row for row in rows if row.status == status]
            return sorted(rows, key=lambda item: item.path)[:limit]
        conditions = []
        if workspace_id:
            conditions.append(CodeFile.workspace_id == workspace_id)
        if language:
            conditions.append(CodeFile.language == language)
        if status:
            conditions.append(CodeFile.status == status)
        return list((await db.scalars(select(CodeFile).where(*conditions).order_by(CodeFile.path.asc()).limit(limit))).all())

    async def find_symbols(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None = None,
        query: str | None = None,
        file_path: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if hasattr(db, "objects"):
            files = {row.id: row for (model, _), row in db.objects.items() if model is CodeFile}
            rows = [row for (model, _), row in db.objects.items() if model is CodeSymbol]
            return [
                serialize_symbol(symbol, file)
                for symbol, file in self._filter_symbol_rows(rows, files, workspace_id, query, file_path, kind, language, limit)
            ]
        stmt = select(CodeSymbol, CodeFile).join(CodeFile, CodeFile.id == CodeSymbol.code_file_id)
        conditions = []
        if workspace_id:
            conditions.append(CodeSymbol.workspace_id == workspace_id)
        if query:
            conditions.append(CodeSymbol.name.ilike(f"%{query}%"))
        if file_path:
            conditions.append(CodeFile.path == file_path)
        if kind:
            conditions.append(CodeSymbol.kind == kind)
        if language:
            conditions.append(CodeSymbol.language == language)
        rows = await db.execute(stmt.where(*conditions).order_by(CodeSymbol.name.asc()).limit(limit))
        return [serialize_symbol(symbol, file) for symbol, file in rows.all()]

    def _filter_symbol_rows(self, rows, files, workspace_id, query, file_path, kind, language, limit):
        output = []
        for row in rows:
            file = files.get(row.code_file_id)
            if workspace_id and row.workspace_id != workspace_id:
                continue
            if query and query.lower() not in row.name.lower():
                continue
            if file_path and (not file or file.path != file_path):
                continue
            if kind and row.kind != kind:
                continue
            if language and row.language != language:
                continue
            output.append((row, file))
        return sorted(output, key=lambda item: item[0].name)[:limit]

    async def find_references(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None = None,
        name: str | None = None,
        symbol_id: UUID | None = None,
        reference_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if hasattr(db, "objects"):
            files = {row.id: row for (model, _), row in db.objects.items() if model is CodeFile}
            refs = [row for (model, _), row in db.objects.items() if model is CodeReference]
            rows = []
            for ref in refs:
                file = files.get(ref.code_file_id)
                if workspace_id and file and file.workspace_id != workspace_id:
                    continue
                if name and name.lower() not in ref.reference_name.lower():
                    continue
                if symbol_id and ref.symbol_id != symbol_id:
                    continue
                if reference_type and ref.reference_type != reference_type:
                    continue
                rows.append((ref, file))
            return [
                serialize_reference(ref, file)
                for ref, file in sorted(rows, key=lambda item: (item[1].path if item[1] else "", item[0].line))[:limit]
            ]
        stmt = select(CodeReference, CodeFile).join(CodeFile, CodeFile.id == CodeReference.code_file_id)
        conditions = []
        if workspace_id:
            conditions.append(CodeFile.workspace_id == workspace_id)
        if name:
            conditions.append(CodeReference.reference_name.ilike(f"%{name}%"))
        if symbol_id:
            conditions.append(CodeReference.symbol_id == symbol_id)
        if reference_type:
            conditions.append(CodeReference.reference_type == reference_type)
        rows = await db.execute(stmt.where(*conditions).order_by(CodeFile.path.asc(), CodeReference.line.asc()).limit(limit))
        return [serialize_reference(ref, file) for ref, file in rows.all()]

    async def list_diagnostics(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None = None,
        file_path: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if hasattr(db, "objects"):
            files = {row.id: row for (model, _), row in db.objects.items() if model is CodeFile}
            rows = []
            for diag in [row for (model, _), row in db.objects.items() if model is CodeDiagnostic]:
                file = files.get(diag.code_file_id)
                if workspace_id and diag.workspace_id != workspace_id:
                    continue
                if file_path and (not file or file.path != file_path):
                    continue
                if severity and diag.severity != severity:
                    continue
                rows.append((diag, file))
            return [serialize_diagnostic(diag, file) for diag, file in rows[:limit]]
        stmt = select(CodeDiagnostic, CodeFile).join(CodeFile, CodeFile.id == CodeDiagnostic.code_file_id)
        conditions = []
        if workspace_id:
            conditions.append(CodeDiagnostic.workspace_id == workspace_id)
        if file_path:
            conditions.append(CodeFile.path == file_path)
        if severity:
            conditions.append(CodeDiagnostic.severity == severity)
        rows = await db.execute(stmt.where(*conditions).order_by(CodeDiagnostic.created_at.desc()).limit(limit))
        return [serialize_diagnostic(diag, file) for diag, file in rows.all()]

    async def create_diagnostic(
        self,
        db: AsyncSession,
        *,
        code_file: CodeFile,
        source: str,
        severity: str,
        message: str,
        line: int,
        column: int | None = None,
        code: str | None = None,
        end_line: int | None = None,
        end_column: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodeDiagnostic:
        diag = CodeDiagnostic(
            code_file_id=code_file.id,
            workspace_id=code_file.workspace_id,
            source=source,
            severity=severity,
            code=code,
            message=redact_text(message),
            line=line,
            column=column,
            end_line=end_line,
            end_column=end_column,
            metadata_json=redact_data(metadata or {}),
        )
        db.add(diag)
        await db.flush()
        return diag

    async def code_map(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID | None = None,
        depth: int = 2,
        include_symbols: bool = True,
    ) -> dict[str, Any]:
        files = await self.list_files(db, workspace_id=workspace_id, limit=10_000)
        languages: dict[str, int] = {}
        for file in files:
            languages[file.language or "unknown"] = languages.get(file.language or "unknown", 0) + 1
        if hasattr(db, "objects"):
            symbols = [
                row
                for (model, _), row in db.objects.items()
                if model is CodeSymbol and (not workspace_id or row.workspace_id == workspace_id)
            ]
            references = [
                row
                for (model, _), row in db.objects.items()
                if model is CodeReference
                and (
                    not workspace_id
                    or (
                        (file := db.objects.get((CodeFile, row.code_file_id), None)) is not None
                        and file.workspace_id == workspace_id
                    )
                )
            ]
            diagnostics = [
                row
                for (model, _), row in db.objects.items()
                if model is CodeDiagnostic and (not workspace_id or row.workspace_id == workspace_id)
            ]
            symbol_count = len(symbols)
            reference_count = len(references)
            diagnostic_count = len(diagnostics)
            symbols_by_file: dict[UUID, int] = {}
            for symbol in symbols:
                symbols_by_file[symbol.code_file_id] = symbols_by_file.get(symbol.code_file_id, 0) + 1
        else:
            if workspace_id:
                symbol_count = int(
                    await db.scalar(select(func.count()).select_from(CodeSymbol).where(CodeSymbol.workspace_id == workspace_id)) or 0
                )
                reference_count = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(CodeReference)
                        .join(CodeFile, CodeFile.id == CodeReference.code_file_id)
                        .where(CodeFile.workspace_id == workspace_id)
                    )
                    or 0
                )
                diagnostic_count = int(
                    await db.scalar(
                        select(func.count()).select_from(CodeDiagnostic).where(CodeDiagnostic.workspace_id == workspace_id)
                    )
                    or 0
                )
            else:
                symbol_count = int(await db.scalar(select(func.count()).select_from(CodeSymbol)) or 0)
                reference_count = int(await db.scalar(select(func.count()).select_from(CodeReference)) or 0)
                diagnostic_count = int(await db.scalar(select(func.count()).select_from(CodeDiagnostic)) or 0)
            symbols_by_file = {}
            rows = await db.execute(select(CodeSymbol.code_file_id, func.count()).group_by(CodeSymbol.code_file_id))
            for file_id, count in rows.all():
                symbols_by_file[file_id] = int(count)
        return {
            "file_count": len(files),
            "symbol_count": symbol_count,
            "reference_count": reference_count,
            "diagnostic_count": diagnostic_count,
            "languages": languages,
            "files": [
                {
                    "id": str(file.id),
                    "path": file.path,
                    "language": file.language,
                    "line_count": file.line_count,
                    "symbol_count": symbols_by_file.get(file.id, 0),
                    "indexed_at": file.indexed_at.isoformat() if file.indexed_at else None,
                    "status": file.status,
                }
                for file in files[: max(depth * 100, 100)]
            ],
            "include_symbols": include_symbols,
            "lsp": {"status": "degraded", "reason": "real LSP client disabled; static DB fallback active"},
        }


codeintel_repository = CodeIntelRepository()
