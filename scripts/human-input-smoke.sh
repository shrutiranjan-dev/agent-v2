#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
DATABASE_URL="${AP_TEST_POSTGRES_URL:-${AP_DATABASE_URL:-}}"
SKIP_EXTERNAL="${SKIP_EXTERNAL:-0}"
VENV_PYTHON=".venv/bin/python"
SMOKE_TMP_DIR="${SMOKE_TMP_DIR:-$(pwd)/.tmp/smokes}"
mkdir -p "${SMOKE_TMP_DIR}"
if command -v cygpath >/dev/null 2>&1; then
  SMOKE_TMP_DIR_PY="$(cygpath -w "${SMOKE_TMP_DIR}")"
else
  SMOKE_TMP_DIR_PY="${SMOKE_TMP_DIR}"
fi
export SMOKE_TMP_DIR SMOKE_TMP_DIR_PY

if [[ "$(uname -s)" != "Linux" && -x ".venv/Scripts/python.exe" ]]; then
  VENV_PYTHON=".venv/Scripts/python.exe"
fi

log() {
  printf '[human-input-smoke] %s\n' "$*"
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
[[ -x "${VENV_PYTHON}" ]] || fail_or_skip "project venv python is required"
[[ -n "${DATABASE_URL}" ]] || fail_or_skip "AP_TEST_POSTGRES_URL or AP_DATABASE_URL must point at the running Postgres database"

log "checking backend health at ${API_BASE}"
curl_json GET /health >"${SMOKE_TMP_DIR}/human-input-smoke-health.json" || fail_or_skip "backend health is unreachable"

log "checking postgres and redis dependencies"
curl_json GET /health/dependencies >"${SMOKE_TMP_DIR}/human-input-smoke-dependencies.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "human-input-smoke-dependencies.json").read_text())
deps = payload.get("dependencies", {})
bad = {
    name: deps.get(name, {}).get("status")
    for name in ("postgres", "redis")
    if deps.get(name, {}).get("status") != "ok"
}
if bad:
    raise SystemExit(f"postgres/redis must be ok: {bad}")
PY

log "selecting model"
curl_json GET /models >"${SMOKE_TMP_DIR}/human-input-smoke-models.json"
MODEL_NAME="$("${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

models = json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "human-input-smoke-models.json").read_text()).get("models", [])
names = [model.get("name") or model.get("model") for model in models]
names = [name for name in names if name]
for preferred in ("llama3.2", "llama", "deepseek", "qwen"):
    for name in names:
        if preferred in name.lower() and "cloud" not in name.lower():
            print(name)
            raise SystemExit
if names:
    print(names[0])
PY
)"
[[ -n "${MODEL_NAME}" ]] || fail_or_skip "No Ollama model returned by /models"

log "creating session"
curl_json POST /sessions "{\"title\":\"Human input smoke\",\"agent_id\":\"general\",\"model_name\":\"${MODEL_NAME}\"}" >"${SMOKE_TMP_DIR}/human-input-smoke-session.json"
SESSION_ID="$("${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

print(json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "human-input-smoke-session.json").read_text())["session"]["id"])
PY
)"

log "seeding deterministic waiting question"
SEED_BODY="{\"session_id\":\"${SESSION_ID}\",\"question\":\"Continue smoke run?\",\"choices\":[\"yes\",\"no\"],\"allow_free_text\":false}"
if ! curl_json POST /human-input/test/seed "${SEED_BODY}" >"${SMOKE_TMP_DIR}/human-input-smoke-seed.json"; then
  fail_or_skip "human input test seed failed. Start backend with AP_ENABLE_TEST_ENDPOINTS=true and APP_ENV!=production."
fi
REQUEST_ID="$("${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

print(json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "human-input-smoke-seed.json").read_text())["request"]["id"])
PY
)"

log "answering human input request ${REQUEST_ID}"
curl_json POST "/human-input/${REQUEST_ID}/answer" '{"answer":"yes"}' >"${SMOKE_TMP_DIR}/human-input-smoke-answer.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "human-input-smoke-answer.json").read_text())
if payload["request"]["status"] != "answered":
    raise SystemExit(f"request not answered: {payload}")
if payload["agent_run"]["status"] != "resume_queued":
    raise SystemExit(f"resume was not queued: {payload}")
if "queue_job" not in payload:
    raise SystemExit(f"missing queue job: {payload}")
PY

log "waiting for worker resume"
for _ in $(seq 1 40); do
  curl_json GET "/sessions/${SESSION_ID}" >"${SMOKE_TMP_DIR}/human-input-smoke-detail.json"
  if "${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
payload = json.loads((tmp_dir / "human-input-smoke-detail.json").read_text())
session = payload["session"]
tool_calls = payload.get("tool_calls", [])
events = []
try:
    events = json.loads((tmp_dir / "human-input-smoke-events.json").read_text()).get("events", [])
except FileNotFoundError:
    pass
if session["status"] == "idle" and sum(1 for call in tool_calls if call["tool_name"] == "question.ask" and call["status"] == "completed") == 1:
    raise SystemExit(0)
raise SystemExit(1)
PY
  then
    break
  fi
  curl_json GET "/sessions/${SESSION_ID}/events" >"${SMOKE_TMP_DIR}/human-input-smoke-events.json" || true
  sleep 1
done

curl_json GET "/sessions/${SESSION_ID}/events" >"${SMOKE_TMP_DIR}/human-input-smoke-events.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
detail = json.loads((tmp_dir / "human-input-smoke-detail.json").read_text())
events = json.loads((tmp_dir / "human-input-smoke-events.json").read_text()).get("events", [])
event_types = {event.get("event_type") or event.get("type") for event in events}
required = {
    "question.requested",
    "question.answered",
    "agent_run.resume_queued",
    "agent_run.resumed_from_human_input",
    "tool_call.completed",
}
missing = sorted(required - event_types)
if missing:
    raise SystemExit(f"missing events {missing}; got {sorted(event_types)}")
tool_calls = detail.get("tool_calls", [])
completed = [call for call in tool_calls if call["tool_name"] == "question.ask" and call["status"] == "completed"]
if len(completed) != 1:
    raise SystemExit(f"expected exactly one completed question.ask tool call, got {completed}")
if detail["session"]["status"] != "idle":
    raise SystemExit(f"session did not return idle: {detail['session']}")
print("human input smoke ok")
PY
