#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
SKIP_EXTERNAL="${SKIP_EXTERNAL:-0}"

log() {
  printf '[runtime-smoke] %s\n' "$*"
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

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail_or_skip "Required command '$1' is not installed."
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

require_cmd curl
require_cmd python3

log "checking backend health at ${API_BASE}"
curl_json GET /health >/tmp/runtime-smoke-health.json || fail_or_skip "Backend health is unreachable. Start the stack with: docker compose up --build"

log "checking dependency health"
curl_json GET /health/dependencies >/tmp/runtime-smoke-dependencies.json
python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("/tmp/runtime-smoke-dependencies.json").read_text())
bad = {
    name: value
    for name, value in payload.get("dependencies", {}).items()
    if value.get("status") not in {"ok", "degraded"}
}
if bad:
    raise SystemExit(f"dependency health has failures: {bad}")
print("dependency health ok/degraded")
PY

if [[ -n "${AP_TEST_POSTGRES_URL:-${AP_DATABASE_URL:-}}" ]]; then
  log "running migration smoke"
  scripts/db-migration-smoke.sh
else
  fail_or_skip "AP_TEST_POSTGRES_URL is not set. Example: export AP_TEST_POSTGRES_URL='postgresql+psycopg://agent:agent@localhost:5432/agent_platform'"
fi

log "checking agents endpoint"
curl_json GET '/agents?include_hidden=true' >/tmp/runtime-smoke-agents.json
python3 - <<'PY'
import json
from pathlib import Path

agents = json.loads(Path("/tmp/runtime-smoke-agents.json").read_text()).get("agents", [])
required = {"build", "plan", "general", "explore", "summary", "compaction"}
present = {agent.get("id") for agent in agents}
missing = sorted(required - present)
if missing:
    raise SystemExit(f"missing native agents: {missing}")
print("agents ok")
PY

log "checking models endpoint"
curl_json GET /models >/tmp/runtime-smoke-models.json
MODEL_NAME="$(python3 - <<'PY'
import json
from pathlib import Path

models = json.loads(Path("/tmp/runtime-smoke-models.json").read_text()).get("models", [])
preferred = ("llama3.2", "llama", "deepseek", "qwen")
local_names = []
for model in models:
    name = model.get("name") or model.get("model")
    if name:
        local_names.append(name)
for prefix in preferred:
    for name in local_names:
        if prefix in name.lower() and "cloud" not in name.lower():
            print(name)
            raise SystemExit
for name in local_names:
    if "cloud" not in name.lower():
        print(name)
        raise SystemExit
if local_names:
    print(local_names[0])
PY
)"

log "creating session"
SESSION_BODY='{"title":"Runtime smoke","agent_id":"general"'
if [[ -n "${MODEL_NAME}" ]]; then
  SESSION_BODY="${SESSION_BODY},\"model_name\":\"${MODEL_NAME}\""
fi
SESSION_BODY="${SESSION_BODY}}"
curl_json POST /sessions "${SESSION_BODY}" >/tmp/runtime-smoke-session.json
SESSION_ID="$(python3 - <<'PY'
import json
from pathlib import Path

print(json.loads(Path("/tmp/runtime-smoke-session.json").read_text())["session"]["id"])
PY
)"
export SESSION_ID
log "created session ${SESSION_ID}"

if [[ -z "${MODEL_NAME}" ]]; then
  fail_or_skip "No Ollama model returned by /models; skipping prompt send. Pull a model with scripts/pull-ollama-models.sh"
fi

log "sending simple prompt with ${MODEL_NAME}"
curl_json POST "/sessions/${SESSION_ID}/messages" '{"content":"Return exactly this JSON object and no prose: {\"type\":\"final\",\"content\":\"runtime smoke ok\"}","agent_id":"general"}' >/tmp/runtime-smoke-message.json || fail_or_skip "Prompt send failed. Check Ollama model availability and backend logs."

log "waiting for queued run to complete"
python3 - <<'PY'
import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

api_base = os.environ.get("API_BASE", "http://localhost:8000")
session_id = os.environ["SESSION_ID"]
transient = {"queued", "running", "resume_queued"}
last = None
for _ in range(90):
    with urlopen(f"{api_base}/sessions/{session_id}", timeout=5) as response:
        payload = json.loads(response.read())
    status = payload["session"]["status"]
    last = payload
    if status == "idle":
        print("session completed")
        raise SystemExit
    if status == "waiting_permission":
        print("session is waiting for permission")
        raise SystemExit
    if status not in transient:
        raise SystemExit(f"session finished with unexpected status {status}: {payload['session']}")
    time.sleep(2)
Path("/tmp/runtime-smoke-last-session.json").write_text(json.dumps(last or {}, indent=2))
raise SystemExit("queued run did not complete before timeout")
PY

log "checking permission endpoint"
curl_json GET "/permissions?session_id=${SESSION_ID}" >/tmp/runtime-smoke-permissions.json

log "runtime smoke ok"
