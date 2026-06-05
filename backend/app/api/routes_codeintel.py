from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.codeintel.indexer import CodeIndexRequest, workspace_indexer
from backend.app.codeintel.lsp_service import lsp_service
from backend.app.codeintel.repository import codeintel_repository, serialize_code_file
from backend.app.core.config import get_settings
from backend.app.core.security import TenantContext, tenant_context
from backend.app.db.postgres import get_session
from backend.app.runtime.tenant import ensure_runtime_tenant

router = APIRouter(tags=["code-intelligence"])


class CodeIndexApiRequest(BaseModel):
    workspace_path: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    force: bool = False


@router.post("/code/index")
async def index_code(
    payload: CodeIndexApiRequest,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    try:
        result = await workspace_indexer.index_workspace(
            db,
            workspace_root=get_settings().workspace_root,
            request=CodeIndexRequest(
                workspace_path=payload.workspace_path,
                include=payload.include,
                exclude=payload.exclude,
                force=payload.force,
            ),
            organization_id=runtime_tenant.organization_id,
            project_id=runtime_tenant.project_id,
            workspace_id=runtime_tenant.workspace_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await db.commit()
    return {
        "files_indexed": result.files_indexed,
        "files_skipped": result.files_skipped,
        "symbols_found": result.symbols_found,
        "diagnostics_found": result.diagnostics_found,
        "errors": result.errors,
    }


@router.get("/code/files")
async def list_code_files(
    language: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    rows = await codeintel_repository.list_files(
        db,
        workspace_id=runtime_tenant.workspace_id,
        language=language,
        status=status,
        limit=limit,
    )
    return {"files": [serialize_code_file(row) for row in rows]}


@router.get("/code/symbols")
async def list_code_symbols(
    query: str | None = None,
    file: str | None = None,
    kind: str | None = None,
    language: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    if file:
        rows = await lsp_service.document_symbols(
            db,
            workspace_id=runtime_tenant.workspace_id,
            file_path=file,
            query=query,
            kind=kind,
            language=language,
            limit=limit,
        )
    else:
        rows = await codeintel_repository.find_symbols(
            db,
            workspace_id=runtime_tenant.workspace_id,
            query=query,
            file_path=file,
            kind=kind,
            language=language,
            limit=limit,
        )
    return {"symbols": rows}


@router.get("/code/definition")
async def code_definition(
    name: str | None = None,
    file: str | None = None,
    line: int | None = Query(default=None, ge=1),
    column: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    if not name and not (file and line):
        raise HTTPException(status_code=422, detail="Provide either name or file+line.")
    definition = await lsp_service.goto_definition(
        db,
        workspace_id=runtime_tenant.workspace_id,
        name=name,
        file=file,
        line=line,
        column=column,
    )
    return {"definition": definition, "lsp": lsp_service.status()}


@router.get("/code/references")
async def code_references(
    name: str | None = None,
    symbol_id: UUID | None = None,
    file: str | None = None,
    line: int | None = Query(default=None, ge=1),
    column: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    if not name and not symbol_id and not (file and line):
        raise HTTPException(status_code=422, detail="Provide name, symbol_id, or file+line.")
    references = await lsp_service.find_references(
        db,
        workspace_id=runtime_tenant.workspace_id,
        name=name,
        symbol_id=symbol_id,
        file=file,
        line=line,
        column=column,
        limit=limit,
    )
    return {"references": references, "lsp": lsp_service.status()}


@router.get("/code/diagnostics")
async def code_diagnostics(
    severity: str | None = None,
    file: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    diagnostics = await lsp_service.get_diagnostics(
        db,
        workspace_id=runtime_tenant.workspace_id,
        file_path=file,
        severity=severity,
        limit=limit,
    )
    return {"diagnostics": diagnostics}


@router.get("/code/map")
async def code_map(
    depth: int = Query(default=2, ge=1, le=5),
    include_symbols: bool = True,
    db: AsyncSession = Depends(get_session),
    tenant: TenantContext = Depends(tenant_context),
) -> dict[str, Any]:
    runtime_tenant = await ensure_runtime_tenant(db, tenant)
    return {
        "code_map": await codeintel_repository.code_map(
            db,
            workspace_id=runtime_tenant.workspace_id,
            depth=depth,
            include_symbols=include_symbols,
        )
    }


@router.get("/health/codeintel")
async def codeintel_health() -> dict[str, Any]:
    settings = get_settings()
    status = await lsp_service.health()
    return {
        "status": "ok" if settings.codeintel.enabled else "disabled",
        "indexing_enabled": settings.codeintel.enabled,
        "workspace_root": str(settings.workspace_root),
        "lsp": status,
    }
