#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-${AP_BACKEND_URL:-http://localhost:8000}}"
SKIP_REAL_MCP_IF_SDK_MISSING="${SKIP_REAL_MCP_IF_SDK_MISSING:-0}"
SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED="${SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED:-0}"
PYTHON_BIN="python3"

if [[ -x ".venv/Scripts/python.exe" ]]; then
  PYTHON_BIN=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "real MCP smoke: backend=${BACKEND_URL}"

"${PYTHON_BIN}" - <<'PY'
import json
import os
import urllib.error
import urllib.request
from uuid import uuid4

base = os.environ.get("BACKEND_URL") or os.environ.get("AP_BACKEND_URL") or "http://localhost:8000"
skip_sdk_missing = os.environ.get("SKIP_REAL_MCP_IF_SDK_MISSING") == "1"
skip_test_endpoint = os.environ.get("SKIP_RUNTIME_EXECUTE_IF_TEST_ENDPOINT_DISABLED") == "1"
suffix = uuid4().hex[:8]


def request(path: str, method: str = "GET", body: dict | None = None, *, timeout: int = 60) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def main() -> None:
    health = request("/health")
    if health.get("status") != "ok":
        raise SystemExit(f"backend health failed: {health}")

    mcp_health = request("/health/mcp")
    print("mcp health:", mcp_health)
    if mcp_health.get("sdk_status") == "degraded":
        message = f"SDK_MISSING: {mcp_health.get('reason')}"
        if skip_sdk_missing:
            print(message)
            print("REAL_MCP_STDIO=skipped")
            return
        raise SystemExit(message)
    if not mcp_health.get("stdio_transport"):
        raise SystemExit(f"stdio transport is not available: {mcp_health}")

    server = request(
        "/mcp/servers",
        "POST",
        {
            "name": f"real-smoke-{suffix}",
            "server_type": "stdio",
            "command": "python",
            "args": ["/app/backend/tests/fixtures/fake_mcp_server.py"],
            "cwd": "/workspace",
            "env": {"SECRET_TOKEN": "must-not-leak"},
            "enabled": True,
            "trusted": True,
        },
    )["server"]
    if server["env"].get("SECRET_TOKEN") != "[REDACTED]":
        raise SystemExit(f"MCP env leaked in response: {server['env']}")

    connected = request(f"/mcp/servers/{server['id']}/connect", "POST")["server"]
    if connected["status"] != "connected":
        raise SystemExit(f"fake stdio MCP server did not connect: {connected}")

    tools = request(f"/mcp/servers/{server['id']}/discover", "POST")["tools"]
    echo = next((tool for tool in tools if tool["name"] == "echo"), None)
    if not echo:
        raise SystemExit(f"echo tool was not discovered: {tools}")
    if echo["enabled"]:
        raise SystemExit("discovered MCP tool was auto-enabled unexpectedly")

    enabled = request(f"/mcp/tools/{echo['id']}/enable", "POST")["tool"]
    native_tools = request("/tools")["tools"]
    if not any(tool["name"] == enabled["full_name"] for tool in native_tools):
        raise SystemExit(f"enabled MCP tool is missing from /tools: {enabled['full_name']}")

    try:
        runtime = request(
            "/mcp/test/execute-tool",
            "POST",
            {"tool_name": enabled["full_name"], "input": {"text": "hello"}},
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc) and skip_test_endpoint:
            print("MCP_RUNTIME_EXECUTION=skipped_test_endpoint_disabled")
        else:
            raise
    else:
        if runtime.get("status") != "waiting_permission" or not runtime.get("permission_request_id"):
            raise SystemExit(f"MCP runtime path did not enter permission flow: {runtime}")
        print("MCP_RUNTIME_EXECUTION=permission_flow_verified")

    latest_health = request("/health/mcp")
    if not latest_health.get("real_mcp"):
        raise SystemExit(f"health did not report real MCP after stdio validation: {latest_health}")

    print("REAL_MCP_STDIO=passed")


try:
    main()
except RuntimeError as exc:
    raise SystemExit(str(exc)) from exc
PY
