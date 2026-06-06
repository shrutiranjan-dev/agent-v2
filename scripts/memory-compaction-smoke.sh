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
  printf '[memory-compaction-smoke] %s\n' "$*"
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
curl_json GET /health >"${SMOKE_TMP_DIR}/memory-compaction-health.json" || fail_or_skip "backend health is unreachable"

log "checking postgres and redis dependencies"
curl_json GET /health/dependencies >"${SMOKE_TMP_DIR}/memory-compaction-dependencies.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "memory-compaction-dependencies.json").read_text())
deps = payload.get("dependencies", {})
bad = {
    name: deps.get(name, {}).get("status")
    for name in ("postgres", "redis")
    if deps.get(name, {}).get("status") != "ok"
}
if bad:
    raise SystemExit(f"postgres/redis must be ok: {bad}")
PY

log "creating session"
curl_json POST /sessions '{"title":"Memory compaction smoke","agent_id":"general"}' >"${SMOKE_TMP_DIR}/memory-compaction-session.json"
SESSION_ID="$("${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

print(json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "memory-compaction-session.json").read_text())["session"]["id"])
PY
)"

log "seeding queued compaction job"
SEED_BODY="{\"session_id\":\"${SESSION_ID}\",\"message\":\"Older smoke context that should be compacted.\",\"summary_content\":\"Compaction smoke durable summary.\"}"
if ! curl_json POST /memory/test/compaction-seed "${SEED_BODY}" >"${SMOKE_TMP_DIR}/memory-compaction-seed.json"; then
  fail_or_skip "compaction seed failed. Start backend/worker with AP_ENABLE_TEST_ENDPOINTS=true, AP_QUEUE_ENABLED=true, and APP_ENV!=production."
fi

log "waiting for worker compaction"
for _ in $(seq 1 40); do
  curl_json GET "/sessions/${SESSION_ID}/summaries" >"${SMOKE_TMP_DIR}/memory-compaction-summaries.json" || true
  if "${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "memory-compaction-summaries.json").read_text())
summaries = payload.get("summaries", [])
if any(item.get("summary_type") == "compaction" and "Compaction smoke durable summary." in item.get("content", "") for item in summaries):
    raise SystemExit(0)
raise SystemExit(1)
PY
  then
    break
  fi
  sleep 1
done

curl_json GET "/sessions/${SESSION_ID}/summaries" >"${SMOKE_TMP_DIR}/memory-compaction-summaries.json"
curl_json GET "/sessions/${SESSION_ID}/memory" >"${SMOKE_TMP_DIR}/memory-compaction-memory.json"
curl_json GET "/sessions/${SESSION_ID}/events" >"${SMOKE_TMP_DIR}/memory-compaction-events.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
summaries = json.loads((tmp_dir / "memory-compaction-summaries.json").read_text()).get("summaries", [])
memory = json.loads((tmp_dir / "memory-compaction-memory.json").read_text()).get("memory_items", [])
events = json.loads((tmp_dir / "memory-compaction-events.json").read_text()).get("events", [])
if not any(item.get("summary_type") == "compaction" for item in summaries):
    raise SystemExit(f"no active compaction summary: {summaries}")
if not any(item.get("source_type") == "session_summary" for item in memory):
    raise SystemExit(f"no session_summary memory item: {memory}")
event_types = {event.get("event_type") or event.get("type") for event in events}
required = {"compaction.queued", "compaction.started", "compaction.completed", "summary.created", "memory_item.created"}
missing = sorted(required - event_types)
if missing:
    raise SystemExit(f"missing events {missing}; got {sorted(event_types)}")
print("memory compaction smoke ok")
PY
