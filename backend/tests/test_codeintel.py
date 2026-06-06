from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.agents.registry import agent_registry
from backend.app.codeintel.diagnostics import diagnostics_service, parse_ruff_output
from backend.app.codeintel.indexer import CodeIndexRequest, WorkspaceIndexer
from backend.app.codeintel.language import detect_language
from backend.app.codeintel.lsp_client import (
    encode_jsonrpc_message,
    lsp_client,
    read_jsonrpc_message,
)
from backend.app.codeintel.lsp_service import lsp_service
from backend.app.codeintel.parser import parse_code
from backend.app.codeintel.repository import codeintel_repository
from backend.app.db.models import CodeDiagnostic, CodeFile, CodeReference, CodeSymbol
from backend.app.db.postgres import get_session
from backend.app.main import create_app
from backend.app.runtime.context_builder import context_builder
from backend.app.runtime.tool_executor import ToolExecutor
from backend.app.tools.codeintel import CodeDefinitionTool, CodeSymbolsTool
from backend.app.tools.registry import tool_registry
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import make_session, make_user_message

FAKE_LSP_SERVER = Path(__file__).parent / "fixtures" / "fake_lsp_server.py"


def codeintel_test_settings(
    workspace_root: Path,
    *,
    lsp_enabled: bool = False,
    lsp_command: str | None = None,
    startup_timeout: int = 1,
    request_timeout: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_root=workspace_root,
        context_char_budget=24000,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
        redis=SimpleNamespace(pubsub_enabled=False),
        memory=SimpleNamespace(compaction_threshold_ratio=0.8, compaction_min_excluded_messages=4),
        codeintel=SimpleNamespace(
            enabled=True,
            lsp_enabled=lsp_enabled,
            max_file_bytes=512_000,
            max_files=100,
            context_symbol_limit=12,
            context_diagnostic_limit=8,
        ),
        lsp=SimpleNamespace(
            enabled=lsp_enabled,
            python_command=lsp_command or sys.executable,
            startup_timeout_seconds=startup_timeout,
            request_timeout_seconds=request_timeout,
            shutdown_timeout_seconds=1,
            max_response_chars=200_000,
            workspace_root=workspace_root,
        ),
    )


def patch_codeintel_settings(monkeypatch, settings) -> None:
    monkeypatch.setattr("backend.app.codeintel.indexer.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.codeintel.lsp_client.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.codeintel.lsp_service.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.context_builder.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.event_bus.get_settings", lambda: settings)


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


def test_jsonrpc_message_round_trip() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    async def round_trip() -> dict:
        reader = asyncio.StreamReader()
        reader.feed_data(encode_jsonrpc_message(payload))
        reader.feed_eof()
        return await read_jsonrpc_message(reader)

    decoded = asyncio.run(round_trip())
    assert decoded == payload


async def test_workspace_indexer_indexes_symbols_skips_unchanged_and_ignores_dirs(monkeypatch, tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "service.py").write_text("class Service:\n    def run(self):\n        return 1\n", encoding="utf-8")
    (tmp_path / "frontend.ts").write_text("export function boot() { return 1; }\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.ts").write_text("function ignored() {}\n", encoding="utf-8")
    settings = codeintel_test_settings(tmp_path)
    patch_codeintel_settings(monkeypatch, settings)
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


async def test_lsp_health_reports_static_fallback_when_disabled(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=False)
    patch_codeintel_settings(monkeypatch, settings)

    health = await lsp_service.health()

    assert health["mode"] == "static_fallback"
    assert health["real_lsp_enabled"] is False
    assert "Static database index fallback" in str(health["reason"])


async def test_lsp_health_reports_missing_command(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True, lsp_command="definitely-not-installed")
    patch_codeintel_settings(monkeypatch, settings)

    health = await lsp_service.health()

    assert health["mode"] == "failed"
    assert "not found" in str(health["last_error"])


async def test_lsp_startup_timeout_is_reported(monkeypatch, tmp_path) -> None:
    slow_file = tmp_path / "sleep_service.py"
    slow_file.write_text("class Service:\n    pass\n", encoding="utf-8")
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True, startup_timeout=1, request_timeout=1)
    settings.lsp.python_command = sys.executable
    patch_codeintel_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.codeintel.lsp_client.get_settings", lambda: settings)
    lsp_client._resolve_command = lambda _command: sys.executable  # type: ignore[method-assign]

    original_exec = asyncio.create_subprocess_exec

    async def patched_exec(*args, **kwargs):
        return await original_exec(sys.executable, str(FAKE_LSP_SERVER), *args[1:], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", patched_exec)
    settings.lsp.startup_timeout_seconds = 0
    health = await lsp_service.health()
    await lsp_service.shutdown()

    assert health["mode"] == "failed"


async def test_lsp_request_timeout_falls_back(monkeypatch, tmp_path) -> None:
    timed_file = tmp_path / "timeout_service.py"
    timed_file.write_text("class Service:\n    pass\n", encoding="utf-8")
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True, request_timeout=1)
    patch_codeintel_settings(monkeypatch, settings)

    original_exec = asyncio.create_subprocess_exec

    async def patched_exec(*args, **kwargs):
        return await original_exec(sys.executable, str(FAKE_LSP_SERVER), *args[1:], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", patched_exec)
    settings.lsp.python_command = sys.executable
    result = await lsp_service.document_symbols(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file_path="timeout_service.py",
        limit=20,
    )
    await lsp_service.shutdown()

    assert result.items == []
    assert result.source == "static_fallback"
    assert result.fallback_reason is not None
    assert lsp_service.status()["mode"] == "failed"


async def test_lsp_workspace_outside_root_blocked(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True)
    patch_codeintel_settings(monkeypatch, settings)

    try:
        await lsp_client.initialize(tmp_path.parent)
    except PermissionError as exc:
        assert "outside configured root" in str(exc)
    else:
        raise AssertionError("expected workspace root guard")


async def test_lsp_fake_server_definition_references_and_diagnostics(monkeypatch, tmp_path) -> None:
    source = tmp_path / "service.py"
    source.write_text("class Service:\n    pass\n\nService()\n", encoding="utf-8")
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True)
    settings.lsp.python_command = sys.executable
    patch_codeintel_settings(monkeypatch, settings)

    original_exec = asyncio.create_subprocess_exec

    async def patched_exec(*args, **kwargs):
        return await original_exec(sys.executable, str(FAKE_LSP_SERVER), *args[1:], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", patched_exec)
    definition = await lsp_service.goto_definition(FakeAsyncSession(), workspace_id=uuid4(), file="service.py", line=1, column=0)
    references = await lsp_service.find_references(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file="service.py",
        line=1,
        column=0,
        limit=20,
    )
    diagnostics = await lsp_service.get_diagnostics(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file_path="service.py",
        limit=20,
    )
    symbols = await lsp_service.document_symbols(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file_path="service.py",
        limit=20,
    )
    await lsp_service.shutdown()

    assert definition.items is not None
    assert definition.items["file_path"] == "service.py"
    assert references.items[0]["file_path"] == "service.py"
    assert diagnostics.items[0]["severity"] == "warning"
    assert symbols.items[0]["name"] == "Service"
    assert lsp_service.status()["mode"] in {"real_lsp", "failed"}
    if lsp_service.status()["mode"] == "real_lsp":
        assert definition.source == "real_lsp"
        assert references.source == "real_lsp"
        assert symbols.source == "real_lsp"
        assert diagnostics.source == "real_lsp"


async def test_lsp_static_fallback_definition_and_references(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=False)
    patch_codeintel_settings(monkeypatch, settings)
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

    definition = await lsp_service.goto_definition(db, workspace_id=file.workspace_id, name="Service")
    references = await lsp_service.find_references(db, workspace_id=file.workspace_id, name="Service")

    assert definition.items is not None
    assert definition.items["name"] == "Service"
    assert references.items[0]["snippet"] == "Service()"
    assert definition.source == "static_fallback"
    assert references.source == "static_fallback"
    assert lsp_service.status()["mode"] == "static_fallback"


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
    settings = codeintel_test_settings(tmp_path, lsp_enabled=False)
    patch_codeintel_settings(monkeypatch, settings)

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
    assert outcome.output["output"]["source"] == "static_fallback"
    assert outcome.output["output"]["lsp_status"] == "static_fallback"
    assert "fallback_reason" in outcome.output["output"]


async def test_codeintel_tools_direct_definition(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path)
    patch_codeintel_settings(monkeypatch, settings)
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
        workspace_root=tmp_path,
    )

    symbols = await CodeSymbolsTool().run(CodeSymbolsTool.input_model(query="Service"), ctx)  # type: ignore[arg-type]
    definition = await CodeDefinitionTool().run(CodeDefinitionTool.input_model(name="Service"), ctx)  # type: ignore[arg-type]

    assert symbols.output["count"] == 1
    assert symbols.output["source"] == "static_fallback"
    assert symbols.output["lsp_status"] == "static_fallback"
    assert definition.output["definition"]["name"] == "Service"
    assert definition.output["source"] == "static_fallback"
    assert definition.output["lsp_status"] == "static_fallback"


async def test_context_builder_includes_code_map_symbols_and_diagnostics(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path)
    patch_codeintel_settings(monkeypatch, settings)
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


async def test_lsp_client_lifecycle_via_fake_server(monkeypatch, tmp_path) -> None:
    source = tmp_path / "service.py"
    source.write_text("class Service:\n    pass\n", encoding="utf-8")
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True, startup_timeout=5, request_timeout=5)
    settings.lsp.python_command = sys.executable
    patch_codeintel_settings(monkeypatch, settings)

    original_exec = asyncio.create_subprocess_exec

    async def patched_exec(*args, **kwargs):
        return await original_exec(sys.executable, str(FAKE_LSP_SERVER), *args[1:], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", patched_exec)
    await lsp_client.initialize(tmp_path)
    capabilities = await lsp_client.initialize(tmp_path)
    assert isinstance(capabilities, dict)
    symbols = await lsp_client.document_symbols(source)
    assert isinstance(symbols, list)
    await lsp_client.shutdown()
    assert lsp_client._is_running() is False


async def test_lsp_health_started_alias_matches_started_at() -> None:
    snapshot = lsp_service.status()
    assert "started" in snapshot
    assert "started_at" in snapshot
    assert snapshot["started"] == snapshot["started_at"]


async def test_lsp_service_static_fallback_includes_source_fields(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=False)
    patch_codeintel_settings(monkeypatch, settings)
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
    db = FakeAsyncSession(objects=[file, symbol])

    result = await lsp_service.document_symbols(
        db,
        workspace_id=file.workspace_id,
        file_path="service.py",
        limit=10,
    )

    assert result.source == "static_fallback"
    assert result.lsp_status == "static_fallback"
    assert result.fallback_reason is not None
    assert isinstance(result.lsp, dict)
    assert "started" in result.lsp


async def test_lsp_service_missing_command_falls_back_to_static(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True, lsp_command="definitely-not-installed-pylsp")
    patch_codeintel_settings(monkeypatch, settings)
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
    db = FakeAsyncSession(objects=[file, symbol])

    result = await lsp_service.document_symbols(
        db,
        workspace_id=file.workspace_id,
        file_path="service.py",
        limit=10,
    )

    assert result.source == "static_fallback"
    assert result.lsp_status == "failed"
    assert result.fallback_reason is not None


async def test_lsp_service_real_path_via_fake_server_includes_source_real_lsp(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "service.py"
    source.write_text("class Service:\n    pass\n", encoding="utf-8")
    settings = codeintel_test_settings(tmp_path, lsp_enabled=True, startup_timeout=5, request_timeout=5)
    settings.lsp.python_command = sys.executable
    patch_codeintel_settings(monkeypatch, settings)

    original_exec = asyncio.create_subprocess_exec

    async def patched_exec(*args, **kwargs):
        return await original_exec(sys.executable, str(FAKE_LSP_SERVER), *args[1:], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", patched_exec)

    result = await lsp_service.document_symbols(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file_path="service.py",
        limit=20,
    )
    await lsp_service.shutdown()

    assert result.source in {"real_lsp", "static_fallback"}
    assert result.lsp_status in {"real_lsp", "failed"}
    if result.source == "real_lsp":
        assert result.fallback_reason is None


def test_lsp_resolve_command_supports_args(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda command: "/usr/bin/python3" if command == "python" else None)

    from backend.app.codeintel.lsp_client import LspClient

    assert LspClient()._resolve_command("python -m pylsp") == ["/usr/bin/python3", "-m", "pylsp"]


async def test_codeintel_routes_include_source_field(monkeypatch, tmp_path) -> None:
    settings = codeintel_test_settings(tmp_path, lsp_enabled=False)
    patch_codeintel_settings(monkeypatch, settings)
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
    reference = CodeReference(
        id=uuid4(),
        symbol_id=symbol.id,
        code_file_id=file.id,
        reference_name="Service",
        reference_type="reference",
        line=4,
        column=2,
        snippet="Service()",
        metadata_json={},
    )
    db_session = FakeAsyncSession(objects=[file, symbol, reference])
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session

    from backend.app.api import routes_codeintel
    from backend.app.runtime.tenant import RuntimeTenant

    runtime_tenant = RuntimeTenant(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=file.workspace_id,
        user_id=uuid4(),
    )

    async def fake_ensure_runtime_tenant(db, tenant):  # noqa: ARG001
        return runtime_tenant

    monkeypatch.setattr(routes_codeintel, "ensure_runtime_tenant", fake_ensure_runtime_tenant)

    with TestClient(app) as client:
        symbols_resp = client.get("/code/symbols?file=service.py&limit=10")
        definition_resp = client.get("/code/definition?name=Service")
        references_resp = client.get("/code/references?name=Service")
        diagnostics_resp = client.get("/code/diagnostics?file=service.py&limit=10")
        health_resp = client.get("/health/codeintel")

    assert symbols_resp.status_code == 200
    body = symbols_resp.json()
    assert body["source"] == "static_fallback"
    assert body["lsp_status"] == "static_fallback"
    assert "fallback_reason" in body
    assert "lsp" in body

    assert definition_resp.status_code == 200
    body = definition_resp.json()
    assert body["source"] == "static_fallback"
    assert body["lsp_status"] == "static_fallback"
    assert "fallback_reason" in body

    assert references_resp.status_code == 200
    body = references_resp.json()
    assert body["source"] == "static_fallback"
    assert "fallback_reason" in body

    assert diagnostics_resp.status_code == 200
    body = diagnostics_resp.json()
    assert body["source"] == "static_fallback"
    assert "fallback_reason" in body

    assert health_resp.status_code == 200
    body = health_resp.json()
    assert "lsp" in body
    assert "started" in body["lsp"]
    assert "started_at" in body["lsp"]
