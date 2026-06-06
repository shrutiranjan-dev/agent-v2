from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.main import create_app
from backend.app.mcp.client import McpToolDefinition
from backend.app.mcp.service import McpServerCreate, mcp_service, serialize_mcp_server
from backend.app.mcp.tools import McpWrappedTool
from backend.app.plugins.hooks import hook_registry
from backend.app.plugins.service import PluginLoadRequest, plugin_service, serialize_plugin
from backend.app.plugins.tools import PluginManifestTool
from backend.app.runtime.tool_executor import ToolExecutor
from backend.app.tools.registry import tool_registry
from backend.tests.fakes import FakeAsyncSession


async def test_mcp_server_env_redacted_and_connect_failure_recorded(monkeypatch) -> None:
    db = FakeAsyncSession()
    org_id = uuid4()
    project_id = uuid4()
    workspace_id = uuid4()
    server = await mcp_service.create_server(
        db,
        McpServerCreate(
            organization_id=org_id,
            project_id=project_id,
            workspace_id=workspace_id,
            name="bad",
            server_type="stdio",
            command="definitely-not-installed",
            env={"API_TOKEN": "abc123"},
            enabled=True,
        ),
    )

    connected = await mcp_service.connect(db, server.id)

    assert connected.status == "failed"
    assert "not found" in str(connected.last_error)
    assert serialize_mcp_server(connected)["env"]["API_TOKEN"] == "[REDACTED]"


async def test_mcp_discovered_tool_disabled_by_default_and_wrapper_fails_structured() -> None:
    db = FakeAsyncSession()
    server = await mcp_service.create_server(
        db,
        McpServerCreate(name="demo", server_type="stdio", command="python", enabled=False, trusted=False),
    )
    tool = await mcp_service.upsert_tool(
        db,
        server=server,
        definition=McpToolDefinition(
            name="lookup",
            description="Lookup",
            input_schema={"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]},
        ),
    )

    assert tool.full_name == "mcp.demo.lookup"
    assert tool.enabled is False
    result = await McpWrappedTool(
        name=tool.full_name,
        description=tool.description,
        input_schema=tool.input_schema,
        risk_level=tool.risk_level,
        enabled=True,
    ).run(McpWrappedTool.input_model(term="x"), SimpleNamespace(db=db))
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "mcp_tool_failed"


async def test_plugin_manifest_loads_tools_disabled_by_default_and_redacts(tmp_path) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "sample-plugin",
                "version": "0.1.0",
                "capabilities": ["tools", "hooks"],
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        "risk_level": "low",
                        "metadata": {"token": "secret-value"},
                    }
                ],
                "hooks": ["before_tool_execute"],
            }
        ),
        encoding="utf-8",
    )
    db = FakeAsyncSession()

    plugin = await plugin_service.load(db, PluginLoadRequest(manifest_path=str(manifest), trusted=True))
    tools = await plugin_service.list_tools(db)

    assert plugin.status == "loaded"
    assert plugin.enabled is False
    assert serialize_plugin(plugin)["trusted"] is True
    assert tools[0].full_name == "plugin.sample-plugin.echo"
    assert tools[0].enabled is False
    assert tools[0].metadata_json["token"] == "[REDACTED]"


async def test_plugin_tool_requires_explicit_enabled_trusted_parent(tmp_path) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "sample-plugin",
                "tools": [
                    {
                        "name": "echo",
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        "risk_level": "low",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    db = FakeAsyncSession()
    plugin = await plugin_service.load(db, PluginLoadRequest(manifest_path=str(manifest), trusted=True))
    tool = (await plugin_service.list_tools(db))[0]

    await plugin_service.set_enabled(db, plugin.id, True)
    enabled_tool = await plugin_service.set_tool_enabled(db, tool.id, True)
    result = await PluginManifestTool(
        name=enabled_tool.full_name,
        description=enabled_tool.description,
        input_schema=enabled_tool.input_schema,
        risk_level=enabled_tool.risk_level,
        enabled=True,
    ).run(PluginManifestTool.input_model(text="hello"), SimpleNamespace(db=db))

    assert result.ok
    assert result.output["text"] == "hello"


async def test_plugin_failed_load_uses_stable_name_and_is_idempotent(tmp_path) -> None:
    """A failed manifest load (missing file, bad JSON) must:

    * Persist a row with status='failed' and a stable, path-independent name
      (a hash of the resolved path) so retries with the same path don't
      collide on the (organization_id, name) unique constraint.
    * Be idempotent: a second load of the same missing path returns the
      same plugin id and updates the recorded last_error.
    """
    missing_manifest = tmp_path / "definitely-missing.json"
    db = FakeAsyncSession()
    org_id = uuid4()

    first = await plugin_service.load(
        db,
        PluginLoadRequest(
            manifest_path=str(missing_manifest),
            organization_id=org_id,
            project_id=uuid4(),
            workspace_id=uuid4(),
            trusted=False,
        ),
    )
    assert first.status == "failed"
    assert first.name.startswith("invalid-")
    assert first.id is not None
    # The fallback name must not contain the raw input path (which on
    # PosixPath is interpreted as a single component, leading to unique
    # constraint violations across hosts and retries).
    assert str(missing_manifest) not in first.name

    second = await plugin_service.load(
        db,
        PluginLoadRequest(
            manifest_path=str(missing_manifest),
            organization_id=org_id,
            project_id=uuid4(),
            workspace_id=uuid4(),
            trusted=False,
        ),
    )
    assert second.id == first.id
    assert second.name == first.name
    assert second.status == "failed"
    assert second.last_error is not None


async def test_plugin_hook_called_before_and_after_tool_execute(monkeypatch, tmp_path) -> None:
    hook_registry.clear()
    calls: list[str] = []

    async def before(payload):
        calls.append(f"before:{payload['tool']}")
        return payload

    async def after(payload):
        calls.append(f"after:{payload['tool']}:{payload['ok']}")
        return payload

    hook_registry.register("before_tool_execute", before, plugin_name="test")
    hook_registry.register("after_tool_execute", after, plugin_name="test")
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    settings = SimpleNamespace(
        workspace_root=tmp_path,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
    )
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: settings)
    db = FakeAsyncSession()
    agent = AgentDefinition(
        id="test",
        name="Test",
        description="Test",
        mode="primary",
        model_config=ModelConfig(model="local"),
        system_prompt="test",
        allowed_tools=["read.file"],
        permission_profile="test",
    )

    outcome = await ToolExecutor().execute(
        db,
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        user_id=None,
        agent_run_id=None,
        agent=agent,
        tool_name="read.file",
        input_json={"path": "README.md"},
    )

    hook_registry.clear()
    assert outcome.status == "completed"
    assert calls == ["before:read.file", "after:read.file:True"]


async def test_plugin_tool_registered_with_registry_enters_permission_flow(monkeypatch, tmp_path) -> None:
    full_name = "plugin.sample.echo"
    tool_registry.register(
        PluginManifestTool(
            name=full_name,
            description="Echo",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            risk_level="low",
            enabled=True,
        )
    )
    settings = SimpleNamespace(
        workspace_root=tmp_path,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
    )
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: settings)
    agent = AgentDefinition(
        id="test",
        name="Test",
        description="Test",
        mode="primary",
        model_config=ModelConfig(model="local"),
        system_prompt="test",
        allowed_tools=[full_name],
        permission_profile="test",
    )
    db = FakeAsyncSession()

    try:
        outcome = await ToolExecutor().execute(
            db,
            organization_id=uuid4(),
            project_id=uuid4(),
            workspace_id=uuid4(),
            session_id=uuid4(),
            user_id=None,
            agent_run_id=uuid4(),
            agent=agent,
            tool_name=full_name,
            input_json={"text": "hello"},
        )
    finally:
        tool_registry.unregister(full_name)

    assert outcome.status == "waiting_permission"
    assert outcome.permission_request_id is not None


def test_mcp_plugin_routes_are_in_openapi() -> None:
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]

    for path in [
        "/mcp/servers",
        "/mcp/servers/{server_id}/enable",
        "/mcp/servers/{server_id}/disable",
        "/mcp/servers/{server_id}/connect",
        "/mcp/servers/{server_id}/disconnect",
        "/mcp/servers/{server_id}/discover",
        "/mcp/tools",
        "/mcp/tools/{tool_id}/enable",
        "/mcp/tools/{tool_id}/disable",
        "/plugins",
        "/plugins/load",
        "/plugins/{plugin_id}/enable",
        "/plugins/{plugin_id}/disable",
        "/plugins/tools",
        "/health/mcp",
        "/health/plugins",
    ]:
        assert path in paths
