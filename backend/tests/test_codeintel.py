from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.agents.registry import agent_registry
from backend.app.codeintel.diagnostics import diagnostics_service, parse_ruff_output
from backend.app.codeintel.indexer import CodeIndexRequest, WorkspaceIndexer
from backend.app.codeintel.language import detect_language
from backend.app.codeintel.lsp_client import lsp_client
from backend.app.codeintel.parser import parse_code
from backend.app.codeintel.repository import codeintel_repository
from backend.app.db.models import CodeDiagnostic, CodeFile, CodeReference, CodeSymbol
from backend.app.main import create_app
from backend.app.runtime.context_builder import context_builder
from backend.app.runtime.tool_executor import ToolExecutor
from backend.app.tools.codeintel import CodeDefinitionTool, CodeSymbolsTool
from backend.app.tools.registry import tool_registry
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import make_session, make_user_message


def code_file(path: str = "app.py", *, workspace_id=None) -> CodeFile:
    now = datetime.now(UTC)
    return CodeFile(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        path=path,
        resolved_path=f"/workspace/{path}",
        language="python",
        size_bytes=12,
        sha256=f"hash-{path}",
        line_count=3,
        status="active",
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def test_language_detection() -> None:
    assert detect_language("backend/app/main.py") == "python"
    assert detect_language("frontend/src/App.tsx") == "typescript"
    assert detect_language("README.md") == "markdown"
    assert detect_language("archive.bin") is None


def test_python_ts_and_markdown_parsers_extract_symbols() -> None:
    py = parse_code(
        "service.py",
        "import os\nclass Service:\n    def run(self):\n        helper()\ndef helper():\n    return os.getcwd()\n",
        "python",
    )
    ts = parse_code(
        "app.ts",
        "import { x } from './x';\nexport class Widget {}\nexport function makeThing() { return x(); }\n",
        "typescript",
    )
    md = parse_code("README.md", "# Title\n## Install\n", "markdown")

    assert {symbol.name for symbol in py.symbols} >= {"Service", "run", "helper"}
    assert any(ref.reference_name == "os" and ref.reference_type == "import" for ref in py.references)
    assert {symbol.name for symbol in ts.symbols} >= {"Widget", "makeThing"}
    assert [symbol.name for symbol in md.symbols] == ["Title", "Install"]


async def test_workspace_indexer_indexes_symbols_skips_unchanged_and_ignores_dirs(monkeypatch, tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "service.py").write_text("class Service:\n    def run(self):\n        return 1\n", encoding="utf-8")
    (tmp_path / "frontend.ts").write_text("export function boot() { return 1; }\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.ts").write_text("function ignored() {}\n", encoding="utf-8")
    settings = SimpleNamespace(
        workspace_root=tmp_path,
        codeintel=SimpleNamespace(max_file_bytes=512_000, max_files=100),
    )
    monkeypatch.setattr("backend.app.codeintel.indexer.get_settings", lambda: settings)
    db = FakeAsyncSession()
    indexer = WorkspaceIndexer()
    organization_id = uuid4()
    project_id = uuid4()
    workspace_id = uuid4()

    first = await indexer.index_workspace(
        db,
        workspace_root=tmp_path,
        request=CodeIndexRequest(force=False),
        organization_id=organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    second = await indexer.index_workspace(
        db,
        workspace_root=tmp_path,
        request=CodeIndexRequest(force=False),
        organization_id=organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
    )

    symbols = [row for row in db.objects.values() if isinstance(row, CodeSymbol)]
    files = [row.path for row in db.objects.values() if isinstance(row, CodeFile)]
    assert first.files_indexed == 2
    assert first.symbols_found >= 2
    assert second.files_skipped >= 2
    assert "node_modules/skip.ts" not in files
    assert {symbol.name for symbol in symbols} >= {"Service", "run", "boot"}


async def test_diagnostics_parse_and_ingest() -> None:
    file = code_file("backend/app/main.py")
    db = FakeAsyncSession(objects=[file])
    parsed = parse_ruff_output("backend/app/main.py:12:4: F401 imported but unused\n")
    created = await diagnostics_service.ingest(
        db,
        workspace_id=file.workspace_id,
        diagnostics=parsed,
    )

    assert created[0].source == "ruff"
    assert created[0].severity == "warning"
    assert created[0].code == "F401"
    assert "unused" in created[0].message


async def test_lsp_static_fallback_definition_and_references() -> None:
    file = code_file("service.py")
    symbol = CodeSymbol(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        name="Service",
        kind="class",
        language="python",
        start_line=2,
        end_line=5,
        signature="class Service",
        metadata_json={},
    )
    reference = CodeReference(
        id=uuid4(),
        symbol_id=symbol.id,
        code_file_id=file.id,
        reference_name="Service",
        reference_type="reference",
        line=8,
        column=4,
        snippet="Service()",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[file, symbol, reference])

    definition = await lsp_client.goto_definition(db, workspace_id=file.workspace_id, name="Service")
    references = await lsp_client.find_references(db, workspace_id=file.workspace_id, name="Service")

    assert definition is not None
    assert definition["name"] == "Service"
    assert references[0]["snippet"] == "Service()"
    assert lsp_client.status()["mode"] == "static_fallback"


async def test_codeintel_repository_code_map_counts() -> None:
    file = code_file("service.py")
    symbol = CodeSymbol(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        name="run",
        kind="function",
        language="python",
        start_line=1,
        metadata_json={},
    )
    diagnostic = CodeDiagnostic(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        source="ruff",
        severity="error",
        message="boom",
        line=1,
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[file, symbol, diagnostic])

    code_map = await codeintel_repository.code_map(db, workspace_id=file.workspace_id)

    assert code_map["file_count"] == 1
    assert code_map["symbol_count"] == 1
    assert code_map["diagnostic_count"] == 1
    assert code_map["languages"] == {"python": 1}


async def test_codeintel_tools_registered_and_execute_with_tool_executor(monkeypatch, tmp_path) -> None:
    session = make_session(agent_id="explore")
    message = make_user_message(session, "find Service")
    file = code_file("service.py", workspace_id=session.workspace_id)
    symbol = CodeSymbol(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        name="Service",
        kind="class",
        language="python",
        start_line=1,
        metadata_json={},
    )
    db = FakeAsyncSession(messages=[message], objects=[session, file, symbol])
    settings = SimpleNamespace(
        workspace_root=tmp_path,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
    )
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: settings)

    assert {"code.index", "code.symbols", "code.definition", "code.references", "code.diagnostics", "code.map"} <= set(
        tool_registry.names()
    )
    outcome = await ToolExecutor().execute(
        db,
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        user_id=session.created_by_user_id,
        agent_run_id=None,
        agent=agent_registry.get("explore"),
        tool_name="code.symbols",
        input_json={"query": "Service"},
    )

    assert outcome.status == "completed"
    assert outcome.output is not None
    assert outcome.output["output"]["symbols"][0]["name"] == "Service"


async def test_codeintel_tools_direct_definition() -> None:
    file = code_file("service.py")
    symbol = CodeSymbol(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        name="Service",
        kind="class",
        language="python",
        start_line=1,
        metadata_json={},
    )
    session = make_session()
    db = FakeAsyncSession(objects=[file, symbol])
    ctx = SimpleNamespace(
        db=db,
        workspace_id=file.workspace_id,
        organization_id=session.organization_id,
        project_id=session.project_id,
        session_id=session.id,
        agent_run_id=None,
        tool_call_id=None,
        agent_id="explore",
        workspace_root="/workspace",
    )

    symbols = await CodeSymbolsTool().run(CodeSymbolsTool.input_model(query="Service"), ctx)  # type: ignore[arg-type]
    definition = await CodeDefinitionTool().run(CodeDefinitionTool.input_model(name="Service"), ctx)  # type: ignore[arg-type]

    assert symbols.output["count"] == 1
    assert definition.output["definition"]["name"] == "Service"


async def test_context_builder_includes_code_map_symbols_and_diagnostics() -> None:
    session = make_session()
    message = make_user_message(session, "Please inspect Service")
    file = code_file("service.py", workspace_id=session.workspace_id)
    symbol = CodeSymbol(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        name="Service",
        kind="class",
        language="python",
        start_line=1,
        metadata_json={},
    )
    diagnostic = CodeDiagnostic(
        id=uuid4(),
        code_file_id=file.id,
        workspace_id=file.workspace_id,
        source="ruff",
        severity="error",
        message="syntax problem",
        line=3,
        metadata_json={},
    )
    db = FakeAsyncSession(messages=[message], objects=[session, file, symbol, diagnostic])

    bundle = await context_builder.build(db, session=session, agent=agent_registry.get("explore"))

    assert "Code intelligence:" in bundle.prompt
    assert "Service" in bundle.prompt
    assert "syntax problem" in bundle.prompt
    assert "class Service:" not in bundle.prompt


def test_codeintel_routes_are_in_openapi() -> None:
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]

    assert "/code/index" in paths
    assert "/code/files" in paths
    assert "/code/symbols" in paths
    assert "/code/definition" in paths
    assert "/code/references" in paths
    assert "/code/diagnostics" in paths
    assert "/code/map" in paths
    assert "/health/codeintel" in paths
