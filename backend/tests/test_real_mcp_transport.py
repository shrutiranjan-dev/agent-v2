from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.mcp.client import mcp_client
from backend.app.mcp.registry import sync_mcp_tools
from backend.app.mcp.service import McpServerCreate, mcp_service, serialize_mcp_server
from backend.app.mcp.tools import McpWrappedTool
from backend.app.runtime.tool_executor import ToolExecutor
from backend.app.tools.registry import tool_registry
from backend.tests.fakes import FakeAsyncSession

FAKE_MCP_SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def mcp_test_settings(workspace_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_root=workspace_root,
        runtime=SimpleNamespace(max_tool_repeats=3, external_write_policy="deny"),
        mcp=SimpleNamespace(
            enabled=True,
            connect_timeout_seconds=10,
            call_timeout_seconds=30,
            shutdown_timeout_seconds=5,
            allow_untrusted_stdio=False,
            allowed_stdio_commands=["python", "python3", Path(sys.executable).name, sys.executable],
            env_allowlist=[],
            max_response_chars=20000,
        ),
    )


async def test_real_mcp_sdk_stdio_connect_discover_and_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.mcp.client.get_settings", lambda: mcp_test_settings(tmp_path))
    server = SimpleNamespace(
        enabled=True,
        trusted=True,
        server_type="stdio",
        command=sys.executable,
        args_json=[str(FAKE_MCP_SERVER)],
        env_json={},
        cwd=str(Path.cwd()),
        name="fake",
    )

    status = await mcp_client.connect(server)
    tools = await mcp_client.discover_tools(server)
    result = await mcp_client.call_tool(server, "echo", {"text": "hello"})

    assert status.status == "connected"
    assert tools[0].name == "echo"
    assert tools[0].input_schema["required"] == ["text"]
    assert result["structuredContent"] == {"echo": "hello"}
    assert result["isError"] is False


async def test_real_mcp_discovery_persists_tools_disabled_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.mcp.client.get_settings", lambda: mcp_test_settings(tmp_path))
    db = FakeAsyncSession()
    server = await mcp_service.create_server(
        db,
        McpServerCreate(
            name="fake",
            server_type="stdio",
            command=sys.executable,
            args=[str(FAKE_MCP_SERVER)],
            cwd=str(Path.cwd()),
            enabled=True,
            trusted=True,
        ),
    )

    connected = await mcp_service.connect(db, server.id)
    tools = await mcp_service.discover_tools(db, server.id)

    assert connected.status == "connected"
    assert tools[0].full_name == "mcp.fake.echo"
    assert tools[0].enabled is False


async def test_enabled_mcp_tool_syncs_registry_and_executes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.mcp.client.get_settings", lambda: mcp_test_settings(tmp_path))
    db = FakeAsyncSession()
    server = await mcp_service.create_server(
        db,
        McpServerCreate(
            name="fake",
            server_type="stdio",
            command=sys.executable,
            args=[str(FAKE_MCP_SERVER)],
            cwd=str(Path.cwd()),
            enabled=True,
            trusted=True,
        ),
    )
    [tool] = await mcp_service.discover_tools(db, server.id)
    enabled_tool = await mcp_service.set_tool_enabled(db, tool.id, True)

    await sync_mcp_tools(db)
    try:
        wrapper = tool_registry.get(enabled_tool.full_name)
        result = await wrapper.run(McpWrappedTool.input_model(text="hello"), SimpleNamespace(db=db))
    finally:
        tool_registry.unregister(enabled_tool.full_name)

    assert result.ok
    assert result.output["structuredContent"] == {"echo": "hello"}


async def test_mcp_tool_enters_permission_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.mcp.client.get_settings", lambda: mcp_test_settings(tmp_path))
    settings = mcp_test_settings(tmp_path)
    monkeypatch.setattr("backend.app.runtime.tool_executor.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.runtime.loop_guard.get_settings", lambda: settings)
    full_name = "mcp.fake.echo"
    tool_registry.register(
        McpWrappedTool(
            name=full_name,
            description="Echo",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            risk_level="medium",
            enabled=True,
        )
    )
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


async def test_untrusted_stdio_command_blocked(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.mcp.client.get_settings", lambda: mcp_test_settings(tmp_path))
    server = SimpleNamespace(
        enabled=True,
        trusted=False,
        server_type="stdio",
        command="/bin/sh",
        args_json=[],
        env_json={},
        cwd=str(tmp_path),
        name="unsafe",
    )

    status = await mcp_client.connect(server)

    assert status.status == "failed"
    assert "not allowed" in str(status.reason)


async def test_mcp_env_redaction_and_outside_cwd_guard(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.app.mcp.client.get_settings", lambda: mcp_test_settings(tmp_path))
    server = SimpleNamespace(
        enabled=True,
        trusted=False,
        server_type="stdio",
        command=sys.executable,
        args_json=[],
        env_json={"API_TOKEN": "[REDACTED]", "SAFE_VALUE": "visible"},
        cwd="/",
        name="unsafe",
    )

    status = await mcp_client.connect(server)
    env = mcp_client._build_env(server.env_json)

    assert status.status == "failed"
    assert "outside workspace" in str(status.reason)
    assert env["SAFE_VALUE"] == "visible"
    assert "API_TOKEN" not in env


async def test_mcp_server_response_redacts_env_in_api_shape() -> None:
    db = FakeAsyncSession()
    server = await mcp_service.create_server(
        db,
        McpServerCreate(
            name="redacted",
            server_type="stdio",
            command="python",
            env={"API_TOKEN": "abc123", "SAFE_VALUE": "visible"},
            enabled=False,
        ),
    )

    serialized = serialize_mcp_server(server)

    assert serialized["env"]["API_TOKEN"] == "[REDACTED]"
    assert serialized["env"]["SAFE_VALUE"] == "visible"
