#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-${AP_BACKEND_URL:-http://localhost:8000}}"

echo "mcp/plugin smoke: backend=${BACKEND_URL}"

python3 - <<'PY'
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

base = os.environ.get("BACKEND_URL") or os.environ.get("AP_BACKEND_URL") or "http://localhost:8000"
suffix = uuid4().hex[:8]


def request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


health = request("/health")
if health.get("status") != "ok":
    raise SystemExit(f"backend health failed: {health}")

mcp_health = request("/health/mcp")
plugin_health = request("/health/plugins")
print("mcp health:", mcp_health)
print("plugin health:", plugin_health)

server = request(
    "/mcp/servers",
    "POST",
    {
        "name": f"smoke-invalid-{suffix}",
        "server_type": "stdio",
        "command": "definitely-not-an-mcp-command",
        "args": [],
        "env": {"SECRET_TOKEN": "should-not-leak"},
        "enabled": False,
        "trusted": False,
    },
)["server"]
if server["enabled"] or server["trusted"]:
    raise SystemExit("MCP server was auto-enabled/trusted unexpectedly")
if server["env"].get("SECRET_TOKEN") != "[REDACTED]":
    raise SystemExit(f"MCP env was not redacted: {server['env']}")

enabled = request(f"/mcp/servers/{server['id']}/enable", "POST")["server"]
connected = request(f"/mcp/servers/{server['id']}/connect", "POST")["server"]
if connected["status"] != "failed":
    raise SystemExit(f"invalid MCP command did not fail safely: {connected}")
if not connected.get("last_error"):
    raise SystemExit("MCP failure did not persist last_error")
print("MCP_REAL_SERVER=not_configured")

project_root = Path.cwd()
plugin_dir = project_root / "plugins"
plugin_dir.mkdir(exist_ok=True)
manifest = plugin_dir / ".smoke-sample-plugin.json"
try:
    manifest.write_text(
        json.dumps(
            {
                "name": f"sample-plugin-{suffix}",
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
                    }
                ],
                "hooks": ["before_tool_execute", "after_tool_execute"],
            }
        ),
        encoding="utf-8",
    )
    plugin = request("/plugins/load", "POST", {"manifest_path": "/workspace/plugins/.smoke-sample-plugin.json", "trusted": True})["plugin"]
    if plugin["enabled"]:
        raise SystemExit("Plugin was auto-enabled unexpectedly")
    tools = request("/plugins/tools")["tools"]
    plugin_tools = [tool for tool in tools if tool["plugin_id"] == plugin["id"]]
    if len(plugin_tools) != 1:
        raise SystemExit(f"Expected one plugin tool, got {plugin_tools}")
    if plugin_tools[0]["enabled"]:
        raise SystemExit("Plugin tool was auto-enabled unexpectedly")
    native_tools = request("/tools")["tools"]
    if any(tool["name"] == plugin_tools[0]["full_name"] for tool in native_tools):
        raise SystemExit("Disabled plugin tool leaked into native /tools registry")

    plugin = request(f"/plugins/{plugin['id']}/enable", "POST")["plugin"]
    tool = request(f"/plugins/tools/{plugin_tools[0]['id']}/enable", "POST")["tool"]
    if not plugin["enabled"] or not tool["enabled"]:
        raise SystemExit("Trusted plugin/tool did not enable through explicit controls")
    native_tools = request("/tools")["tools"]
    if not any(item["name"] == tool["full_name"] for item in native_tools):
        raise SystemExit("Enabled plugin tool did not appear in /tools")
finally:
    manifest.unlink(missing_ok=True)

print("mcp/plugin smoke ok")
PY
