from __future__ import annotations

from time import perf_counter
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.codeintel.diagnostics import diagnostics_service
from backend.app.codeintel.indexer import CodeIndexRequest, workspace_indexer
from backend.app.codeintel.lsp_service import lsp_service
from backend.app.codeintel.repository import codeintel_repository
from backend.app.tools.base import BaseTool, ToolContext, ToolResult


class CodeIndexInput(BaseModel):
    workspace_path: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    force: bool = False


class CodeSymbolsInput(BaseModel):
    query: str | None = None
    file: str | None = None
    kind: str | None = None
    language: str | None = None
    limit: int = Field(default=50, ge=1, le=500)


class CodeDefinitionInput(BaseModel):
    name: str | None = None
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=0)


class CodeReferencesInput(BaseModel):
    name: str | None = None
    symbol_id: UUID | None = None
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class CodeDiagnosticsInput(BaseModel):
    severity: str | None = None
    file: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class CodeMapInput(BaseModel):
    depth: int = Field(default=2, ge=1, le=5)
    include_symbols: bool = True


class CodeIntelTool(BaseTool):
    category = "search"
    risk_level = "low"
    requires_workspace = True
    supports_artifacts = False
    timeout_seconds = 20
    max_output_chars = 60000

    def _db(self, ctx: ToolContext):
        if ctx.db is None:
            raise RuntimeError("Code intelligence tools require a database-backed tool context.")
        return ctx.db


class CodeIndexTool(CodeIntelTool):
    name = "code.index"
    title = "Index Code"
    description = "Index workspace files, languages, symbols, imports, and references without reading outside the workspace."
    input_model = CodeIndexInput
    permission_key = "code.index"
    risk_level = "medium"
    timeout_seconds = 60
    examples = [{"force": False}, {"workspace_path": "backend/app", "include": ["*.py"], "force": True}]

    async def run(self, input_data: CodeIndexInput, ctx: ToolContext) -> ToolResult:
        started = perf_counter()
        result = await workspace_indexer.index_workspace(
            self._db(ctx),
            workspace_root=ctx.workspace_root,
            request=CodeIndexRequest(
                workspace_path=input_data.workspace_path,
                include=input_data.include,
                exclude=input_data.exclude,
                force=input_data.force,
            ),
            organization_id=ctx.organization_id,
            project_id=ctx.project_id,
            workspace_id=ctx.workspace_id,
        )
        duration_ms = int((perf_counter() - started) * 1000)
        output = {
            "files_indexed": result.files_indexed,
            "files_skipped": result.files_skipped,
            "symbols_found": result.symbols_found,
            "diagnostics_found": result.diagnostics_found,
            "duration_ms": duration_ms,
            "errors": result.errors,
        }
        return ToolResult(title="Code index completed", output=output, metadata=output)


class CodeSymbolsTool(CodeIntelTool):
    name = "code.symbols"
    title = "Find Symbols"
    description = "Search indexed workspace symbols by name, file, kind, or language."
    input_model = CodeSymbolsInput
    permission_key = "code.symbols"
    examples = [{"query": "AgentRunner", "limit": 20}, {"file": "backend/app/main.py"}]

    async def run(self, input_data: CodeSymbolsInput, ctx: ToolContext) -> ToolResult:
        if input_data.file:
            result = await lsp_service.document_symbols(
                self._db(ctx),
                workspace_id=ctx.workspace_id,
                file_path=input_data.file,
                query=input_data.query,
                kind=input_data.kind,
                language=input_data.language,
                limit=input_data.limit,
            )
            symbols = result.items
            source = result.source
            lsp_status = result.lsp_status
            fallback_reason = result.fallback_reason
            lsp_snapshot = result.lsp
        else:
            symbols = await codeintel_repository.find_symbols(
                self._db(ctx),
                workspace_id=ctx.workspace_id,
                query=input_data.query,
                file_path=input_data.file,
                kind=input_data.kind,
                language=input_data.language,
                limit=input_data.limit,
            )
            source = "static_fallback"
            lsp_status = lsp_service.status().get("mode", "static_fallback")
            fallback_reason = "File-scoped LSP requires a file path; static index used."
            lsp_snapshot = lsp_service.status()
        return ToolResult(
            title=f"{len(symbols)} symbol(s)",
            output={
                "symbols": symbols,
                "count": len(symbols),
                "source": source,
                "lsp_status": lsp_status,
                "fallback_reason": fallback_reason,
                "lsp": lsp_snapshot,
            },
            metadata={
                "count": len(symbols),
                "source": source,
                "lsp_status": lsp_status,
                "fallback_reason": fallback_reason,
            },
        )


class CodeDefinitionTool(CodeIntelTool):
    name = "code.definition"
    title = "Go To Definition"
    description = "Find the best indexed definition for a symbol name or source location."
    input_model = CodeDefinitionInput
    permission_key = "code.definition"
    examples = [{"name": "ToolExecutor"}, {"file": "backend/app/main.py", "line": 12, "column": 0}]

    async def run(self, input_data: CodeDefinitionInput, ctx: ToolContext) -> ToolResult:
        if not input_data.name and not (input_data.file and input_data.line):
            return ToolResult.failure(
                code="missing_definition_target",
                message="Provide either name or file+line.",
                recoverable=True,
            )
        result = await lsp_service.goto_definition(
            self._db(ctx),
            workspace_id=ctx.workspace_id,
            name=input_data.name,
            file=input_data.file,
            line=input_data.line,
            column=input_data.column,
        )
        return ToolResult(
            title="Definition found" if result.items else "Definition not found",
            output={
                "definition": result.items,
                "source": result.source,
                "lsp_status": result.lsp_status,
                "fallback_reason": result.fallback_reason,
                "lsp": result.lsp,
            },
            metadata={
                "found": result.items is not None,
                "source": result.source,
                "lsp_status": result.lsp_status,
                "fallback_reason": result.fallback_reason,
            },
        )


class CodeReferencesTool(CodeIntelTool):
    name = "code.references"
    title = "Find References"
    description = "Find indexed references for a symbol id or reference name."
    input_model = CodeReferencesInput
    permission_key = "code.references"
    examples = [{"name": "AgentRunner"}, {"symbol_id": "00000000-0000-0000-0000-000000000000"}]

    async def run(self, input_data: CodeReferencesInput, ctx: ToolContext) -> ToolResult:
        if not input_data.name and not input_data.symbol_id and not (input_data.file and input_data.line):
            return ToolResult.failure(
                code="missing_reference_target",
                message="Provide name, symbol_id, or file+line.",
                recoverable=True,
            )
        result = await lsp_service.find_references(
            self._db(ctx),
            workspace_id=ctx.workspace_id,
            name=input_data.name,
            symbol_id=input_data.symbol_id,
            file=input_data.file,
            line=input_data.line,
            column=input_data.column,
            limit=input_data.limit,
        )
        references = result.items
        return ToolResult(
            title=f"{len(references)} reference(s)",
            output={
                "references": references,
                "count": len(references),
                "source": result.source,
                "lsp_status": result.lsp_status,
                "fallback_reason": result.fallback_reason,
                "lsp": result.lsp,
            },
            metadata={
                "count": len(references),
                "source": result.source,
                "lsp_status": result.lsp_status,
                "fallback_reason": result.fallback_reason,
            },
        )


class CodeDiagnosticsTool(CodeIntelTool):
    name = "code.diagnostics"
    title = "List Diagnostics"
    description = "List normalized code diagnostics from indexed/static ingestion sources."
    input_model = CodeDiagnosticsInput
    permission_key = "code.diagnostics"
    examples = [{"severity": "error", "limit": 25}, {"file": "backend/app/main.py"}]

    async def run(self, input_data: CodeDiagnosticsInput, ctx: ToolContext) -> ToolResult:
        result = await lsp_service.get_diagnostics(
            self._db(ctx),
            workspace_id=ctx.workspace_id,
            file_path=input_data.file,
            severity=input_data.severity,
            limit=input_data.limit,
        )
        diagnostics = result.items
        return ToolResult(
            title=f"{len(diagnostics)} diagnostic(s)",
            output={
                "diagnostics": diagnostics,
                "count": len(diagnostics),
                "source": result.source,
                "lsp_status": result.lsp_status,
                "fallback_reason": result.fallback_reason,
                "lsp": result.lsp,
            },
            metadata={
                "count": len(diagnostics),
                "source": result.source,
                "lsp_status": result.lsp_status,
                "fallback_reason": result.fallback_reason,
                "status": diagnostics_service.degraded_status(),
            },
        )


class CodeMapTool(CodeIntelTool):
    name = "code.map"
    title = "Code Map"
    description = "Return a compact indexed repository map with language, file, symbol, and import/reference counts."
    input_model = CodeMapInput
    permission_key = "code.map"
    examples = [{"depth": 2, "include_symbols": True}]

    async def run(self, input_data: CodeMapInput, ctx: ToolContext) -> ToolResult:
        code_map = await codeintel_repository.code_map(
            self._db(ctx),
            workspace_id=ctx.workspace_id,
            depth=input_data.depth,
            include_symbols=input_data.include_symbols,
        )
        return ToolResult(
            title="Code map",
            output={"code_map": code_map},
            metadata={
                "file_count": code_map.get("file_count", 0),
                "symbol_count": code_map.get("symbol_count", 0),
                "diagnostic_count": code_map.get("diagnostic_count", 0),
            },
        )
