#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
DATABASE_URL="${AP_TEST_POSTGRES_URL:-${AP_DATABASE_URL:-}}"
SKIP_EXTERNAL="${SKIP_EXTERNAL:-0}"

log() {
  printf '[permission-resume-smoke] %s\n' "$*"
}

fail_or_skip() {
  local message="$1"
  if [[ "${SKIP_EXTERNAL}" == "1" ]]; then
    log "SKIP: ${message}"
    exit 0
  fi
  log "FAIL: ${message}" >&2
  exit 2
}

curl_json() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  if [[ -n "${body}" ]]; then
    curl -fsS -X "${method}" "${API_BASE}${path}" -H 'content-type: application/json' --data "${body}"
  else
    curl -fsS -X "${method}" "${API_BASE}${path}"
  fi
}

command -v curl >/dev/null 2>&1 || fail_or_skip "curl is required"
[[ -x .venv/bin/python ]] || fail_or_skip ".venv/bin/python is required"
[[ -n "${DATABASE_URL}" ]] || fail_or_skip "AP_TEST_POSTGRES_URL or AP_DATABASE_URL must point at the running Postgres database"

log "checking backend health at ${API_BASE}"
curl_json GET /health >/tmp/permission-smoke-health.json || fail_or_skip "backend health is unreachable"

log "checking queue worker dependency state"
curl_json GET /health/dependencies >/tmp/permission-smoke-dependencies.json
.venv/bin/python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("/tmp/permission-smoke-dependencies.json").read_text())
redis_status = payload.get("dependencies", {}).get("redis", {}).get("status")
postgres_status = payload.get("dependencies", {}).get("postgres", {}).get("status")
if redis_status != "ok" or postgres_status != "ok":
    raise SystemExit(f"postgres/redis must be ok: {payload}")
PY

log "selecting model"
curl_json GET /models >/tmp/permission-smoke-models.json
MODEL_NAME="$(.venv/bin/python - <<'PY'
import json
from pathlib import Path

models = json.loads(Path("/tmp/permission-smoke-models.json").read_text()).get("models", [])
preferred = ("llama3.2", "llama", "deepseek", "qwen")
names = [model.get("name") or model.get("model") for model in models]
names = [name for name in names if name]
for prefix in preferred:
    for name in names:
        if prefix in name.lower() and "cloud" not in name.lower():
            print(name)
            raise SystemExit
for name in names:
    if "cloud" not in name.lower():
        print(name)
        raise SystemExit
if names:
    print(names[0])
PY
)"
[[ -n "${MODEL_NAME}" ]] || fail_or_skip "No Ollama model returned by /models"

log "creating build session"
curl_json POST /sessions "{\"title\":\"Permission resume smoke\",\"agent_id\":\"build\",\"model_name\":\"${MODEL_NAME}\"}" >/tmp/permission-smoke-session.json
SESSION_ID="$(.venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("/tmp/permission-smoke-session.json").read_text())["session"]["id"])
PY
)"
export SESSION_ID
export AP_DATABASE_URL="${DATABASE_URL}"

log "seeding pending write.file permission for session ${SESSION_ID}"
.venv/bin/python - <<'PY' >/tmp/permission-smoke-seeded.json
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg

from backend.app.runtime.loop_guard import input_hash

url = os.environ["AP_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg", "")
session_id = os.environ["SESSION_ID"]
target_path = f"tmp/permission-resume-smoke-{uuid4().hex}.txt"
tool_input = {"path": target_path, "content": "permission resume smoke ok\n"}
digest = input_hash(tool_input)
now = datetime.now(timezone.utc)
run_id = str(uuid4())
message_id = str(uuid4())
tool_call_id = str(uuid4())
permission_request_id = str(uuid4())

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select organization_id, project_id, workspace_id, created_by_user_id, agent_id, model_provider, model_name from sessions where id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"session not found: {session_id}")
        organization_id, project_id, workspace_id, user_id, agent_id, model_provider, model_name = row
        cur.execute(
            """
            insert into messages (
              id, organization_id, project_id, workspace_id, session_id, role, content, parts, metadata_json, created_at, updated_at
            ) values (%s,%s,%s,%s,%s,'user',%s,%s::jsonb,%s::jsonb,%s,%s)
            """,
            (
                message_id,
                organization_id,
                project_id,
                workspace_id,
                session_id,
                'Approve the pending write.file permission, then return {"type":"final","content":"permission resume smoke ok"}.',
                json.dumps([{"type": "text", "text": "permission resume smoke"}]),
                json.dumps({"smoke": "permission_resume"}),
                now,
                now,
            ),
        )
        cur.execute(
            """
            insert into agent_runs (
              id, organization_id, project_id, workspace_id, session_id, agent_id, model_provider, model_name,
              status, step_count, started_at, created_at, updated_at
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,'waiting_permission',0,%s,%s,%s)
            """,
            (run_id, organization_id, project_id, workspace_id, session_id, agent_id, model_provider, model_name, now, now, now),
        )
        cur.execute(
            """
            insert into tool_calls (
              id, organization_id, project_id, workspace_id, session_id, agent_run_id, agent_id,
              tool_name, input_json, input_hash, status, created_at, updated_at
            ) values (%s,%s,%s,%s,%s,%s,%s,'write.file',%s::jsonb,%s,'waiting_permission',%s,%s)
            """,
            (tool_call_id, organization_id, project_id, workspace_id, session_id, run_id, agent_id, json.dumps(tool_input), digest, now, now),
        )
        cur.execute(
            """
            insert into permission_requests (
              id, organization_id, project_id, workspace_id, session_id, agent_run_id, tool_call_id,
              permission_key, resource, action, status, input_json, metadata_json, requested_by_user_id, created_at, updated_at
            ) values (%s,%s,%s,%s,%s,%s,%s,'write.file',%s,'ask','pending',%s::jsonb,%s::jsonb,%s,%s,%s)
            """,
            (
                permission_request_id,
                organization_id,
                project_id,
                workspace_id,
                session_id,
                run_id,
                tool_call_id,
                str(Path("/workspace") / target_path),
                json.dumps(tool_input),
                json.dumps({"tool": "write.file", "reason": "permission resume smoke", "input_hash": digest}),
                user_id,
                now,
                now,
            ),
        )
        cur.execute(
            "update tool_calls set permission_request_id = %s, updated_at = %s where id = %s",
            (permission_request_id, now, tool_call_id),
        )
        cur.execute("update sessions set status = 'waiting_permission', updated_at = %s where id = %s", (now, session_id))
    conn.commit()

print(json.dumps({
    "session_id": session_id,
    "run_id": run_id,
    "tool_call_id": tool_call_id,
    "permission_request_id": permission_request_id,
    "target_path": target_path,
}))
PY

PERMISSION_ID="$(.venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("/tmp/permission-smoke-seeded.json").read_text())["permission_request_id"])
PY
)"
TOOL_CALL_ID="$(.venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("/tmp/permission-smoke-seeded.json").read_text())["tool_call_id"])
PY
)"
TARGET_PATH="$(.venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("/tmp/permission-smoke-seeded.json").read_text())["target_path"])
PY
)"
export PERMISSION_ID TOOL_CALL_ID TARGET_PATH

log "approving permission ${PERMISSION_ID}"
curl_json POST "/permissions/${PERMISSION_ID}/approve" '{"message":"permission resume smoke approval"}' >/tmp/permission-smoke-approve.json
.venv/bin/python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/permission-smoke-approve.json").read_text())
if payload.get("agent_run", {}).get("status") != "resume_queued":
    raise SystemExit(f"expected resume_queued response, got {payload}")
if not payload.get("queue_job"):
    raise SystemExit(f"approval response did not include queue_job: {payload}")
print("approval queued")
PY

log "waiting for worker to execute approved tool"
.venv/bin/python - <<'PY'
import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

api_base = os.environ.get("API_BASE", "http://localhost:8000")
session_id = os.environ["SESSION_ID"]
tool_call_id = os.environ["TOOL_CALL_ID"]
target_path = Path(os.environ["TARGET_PATH"])
workspace_target = Path.cwd() / target_path
last = None
for _ in range(120):
    with urlopen(f"{api_base}/sessions/{session_id}", timeout=5) as response:
        payload = json.loads(response.read())
    last = payload
    tool_calls = payload.get("tool_calls", [])
    matches = [call for call in tool_calls if call.get("id") == tool_call_id]
    if matches and matches[0].get("status") == "completed":
        if not workspace_target.exists():
            raise SystemExit(f"tool call completed but file is missing: {workspace_target}")
        if workspace_target.read_text(encoding="utf-8") != "permission resume smoke ok\n":
            raise SystemExit("written file content mismatch")
        break
    if matches and matches[0].get("status") in {"failed", "denied"}:
        raise SystemExit(f"tool call failed: {matches[0]}")
    time.sleep(2)
else:
    Path("/tmp/permission-smoke-last-session.json").write_text(json.dumps(last or {}, indent=2))
    raise SystemExit("approved tool call did not complete before timeout")

with urlopen(f"{api_base}/sessions/{session_id}/events", timeout=5) as response:
    events = json.loads(response.read()).get("events", [])
event_types = [event.get("event_type") for event in events]
required = {"permission.approved", "agent_run.resume_queued", "agent_run.resumed", "tool_call.completed"}
missing = sorted(required - set(event_types))
if missing:
    raise SystemExit(f"missing expected events: {missing}; saw {event_types}")
completed_tool_events = [
    event for event in events
    if event.get("event_type") == "tool_call.completed" and event.get("tool_call_id") == tool_call_id
]
if len(completed_tool_events) != 1:
    raise SystemExit(f"expected exactly one tool_call.completed for {tool_call_id}, got {len(completed_tool_events)}")
print("permission resume completed exactly once")
PY

rm -f "${TARGET_PATH}" 2>/dev/null || docker compose exec -T backend rm -f "/workspace/${TARGET_PATH}" 2>/dev/null || true
log "permission resume smoke ok"
