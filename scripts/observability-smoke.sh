#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
SKIP_EXTERNAL="${SKIP_EXTERNAL:-0}"
SMOKE_TMP_DIR="${SMOKE_TMP_DIR:-$(pwd)/.tmp/smokes}"
mkdir -p "${SMOKE_TMP_DIR}"

if command -v cygpath >/dev/null 2>&1; then
  SMOKE_TMP_DIR_PY="$(cygpath -w "${SMOKE_TMP_DIR}")"
else
  SMOKE_TMP_DIR_PY="${SMOKE_TMP_DIR}"
fi
export API_BASE SMOKE_TMP_DIR_PY

PYTHON=".venv/bin/python"
if [[ "$(uname -s)" != "Linux" && -x ".venv/Scripts/python.exe" ]]; then
  PYTHON=".venv/Scripts/python.exe"
fi
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="python"
fi

log() {
  printf '[observability-smoke] %s\n' "$*"
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
  curl -fsS "${API_BASE}$1"
}

command -v curl >/dev/null 2>&1 || fail_or_skip "curl is required"
if [[ "${PYTHON}" == "python" ]]; then
  command -v python >/dev/null 2>&1 || fail_or_skip "python is required"
else
  [[ -x "${PYTHON}" ]] || fail_or_skip "project venv python is required"
fi

log "checking backend health"
curl_json /health >"${SMOKE_TMP_DIR}/observability-health.json" || fail_or_skip "backend health is unreachable"

log "checking workers and worker stats"
curl_json /workers >"${SMOKE_TMP_DIR}/observability-workers.json"
curl_json /workers/stats >"${SMOKE_TMP_DIR}/observability-worker-stats.json"

log "checking artifacts and sessions"
curl_json '/artifacts?limit=25' >"${SMOKE_TMP_DIR}/observability-artifacts.json"
curl_json /sessions >"${SMOKE_TMP_DIR}/observability-sessions.json"

"${PYTHON}" - <<'PY'
import json
import os
import subprocess
from pathlib import Path

api_base = os.environ["API_BASE"].rstrip("/")
tmp = Path(os.environ["SMOKE_TMP_DIR_PY"])

health = json.loads((tmp / "observability-health.json").read_text())
if health.get("status") != "ok":
    raise SystemExit(f"backend health did not return ok: {health}")

workers = json.loads((tmp / "observability-workers.json").read_text())
if "workers" not in workers:
    raise SystemExit(f"/workers missing workers: {workers}")

worker_stats = json.loads((tmp / "observability-worker-stats.json").read_text())
stats = worker_stats.get("stats", {})
required_stats = {"total", "active", "stale", "claimed_jobs_count", "completed_jobs_count", "failed_jobs_count"}
missing_stats = required_stats - set(stats)
if missing_stats:
    raise SystemExit(f"/workers/stats missing {missing_stats}: {worker_stats}")

artifacts = json.loads((tmp / "observability-artifacts.json").read_text())
for artifact in artifacts.get("artifacts", []):
    if "object_key" in artifact or "bucket" in artifact:
        raise SystemExit(f"artifact list exposed storage internals: {artifact}")

if artifacts.get("artifacts"):
    artifact_id = artifacts["artifacts"][0]["id"]
    detail = subprocess.check_output(["curl", "-fsS", f"{api_base}/artifacts/{artifact_id}"], text=True)
    payload = json.loads(detail)
    artifact = payload.get("artifact", {})
    if "object_key" in artifact or "bucket" in artifact:
        raise SystemExit(f"artifact detail exposed storage internals: {artifact}")
    print("ARTIFACT_DETAIL=passed")
else:
    print("ARTIFACT_DETAIL=skipped reason=no_artifacts")

sessions = json.loads((tmp / "observability-sessions.json").read_text())
if sessions.get("sessions"):
    session_id = sessions["sessions"][0]["id"]
    session_artifacts = subprocess.check_output(["curl", "-fsS", f"{api_base}/sessions/{session_id}/artifacts"], text=True)
    payload = json.loads(session_artifacts)
    for artifact in payload.get("artifacts", []):
        if "object_key" in artifact or "bucket" in artifact:
            raise SystemExit(f"session artifact exposed storage internals: {artifact}")
    print("SESSION_ARTIFACTS=passed")
else:
    print("SESSION_ARTIFACTS=skipped reason=no_sessions")

print("WORKER_OBSERVABILITY=passed")
PY

log "observability smoke ok"
