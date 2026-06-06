#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
DATABASE_URL="${AP_TEST_POSTGRES_URL:-${AP_DATABASE_URL:-}}"
SKIP_EXTERNAL="${SKIP_EXTERNAL:-0}"
QUEUE_SMOKE_MANAGE_WORKER="${QUEUE_SMOKE_MANAGE_WORKER:-0}"
VENV_PYTHON=".venv/bin/python"
SMOKE_TMP_DIR="${SMOKE_TMP_DIR:-$(pwd)/.tmp/smokes}"
mkdir -p "${SMOKE_TMP_DIR}"
if command -v cygpath >/dev/null 2>&1; then
  SMOKE_TMP_DIR_PY="$(cygpath -w "${SMOKE_TMP_DIR}")"
else
  SMOKE_TMP_DIR_PY="${SMOKE_TMP_DIR}"
fi
export SMOKE_TMP_DIR SMOKE_TMP_DIR_PY

if [[ -x ".venv/Scripts/python.exe" ]]; then
  VENV_PYTHON=".venv/Scripts/python.exe"
fi

log() {
  printf '[queue-worker-smoke] %s\n' "$*"
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

WORKER_PAUSED=0
cleanup() {
  if [[ "${WORKER_PAUSED}" == "1" ]]; then
    log "restarting backend-worker"
    if command -v docker >/dev/null 2>&1; then
      docker compose start backend-worker >/dev/null
    else
      docker-compose start backend-worker >/dev/null
    fi
  fi
}
trap cleanup EXIT

log "checking backend health"
curl_json GET /health >"${SMOKE_TMP_DIR}/queue-worker-health.json" || fail_or_skip "backend health is unreachable"

log "checking queue endpoints"
curl_json GET /queue/stats >"${SMOKE_TMP_DIR}/queue-worker-stats-before.json"
curl_json GET /queue/workers >"${SMOKE_TMP_DIR}/queue-worker-workers.json"

if [[ "${QUEUE_SMOKE_MANAGE_WORKER}" != "0" ]] && { command -v docker >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1; }; then
  log "pausing backend-worker for deterministic queue row checks"
  if command -v docker >/dev/null 2>&1; then
    docker compose stop backend-worker >/dev/null
  else
    docker-compose stop backend-worker >/dev/null
  fi
  WORKER_PAUSED=1
fi

export AP_DATABASE_URL="${DATABASE_URL}"
log "seeding failed and queued queue jobs"
"${VENV_PYTHON}" - <<'PY' >"${SMOKE_TMP_DIR}/queue-worker-seeded.json"
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg

url = os.environ["AP_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg", "")
now = datetime.now(timezone.utc)
failed_job_id = str(uuid4())
queued_job_id = str(uuid4())
failed_key = f"queue-worker-smoke:failed:{failed_job_id}"
queued_key = f"queue-worker-smoke:queued:{queued_job_id}"

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into queue_jobs (
              id, job_type, status, priority, payload, idempotency_key, attempt_count, max_attempts,
              available_at, failed_at, last_error, created_at, updated_at
            ) values (%s,'agent_run','failed',100,%s::jsonb,%s,2,3,%s,%s,%s,%s,%s)
            """,
            (
                failed_job_id,
                json.dumps({"smoke": "queue_worker", "kind": "failed"}),
                failed_key,
                now,
                now,
                "queue worker smoke failure",
                now - timedelta(minutes=2),
                now - timedelta(minutes=2),
            ),
        )
        cur.execute(
            """
            insert into queue_jobs (
              id, job_type, status, priority, payload, idempotency_key, attempt_count, max_attempts,
              available_at, created_at, updated_at
            ) values (%s,'agent_run','queued',100,%s::jsonb,%s,0,3,%s,%s,%s)
            """,
            (
                queued_job_id,
                json.dumps({"smoke": "queue_worker", "kind": "queued"}),
                queued_key,
                now,
                now - timedelta(minutes=1),
                now - timedelta(minutes=1),
            ),
        )
    conn.commit()

print(json.dumps({"failed_job_id": failed_job_id, "queued_job_id": queued_job_id}))
PY

FAILED_JOB_ID="$("${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path
print(json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "queue-worker-seeded.json").read_text())["failed_job_id"])
PY
)"
QUEUED_JOB_ID="$("${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path
print(json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "queue-worker-seeded.json").read_text())["queued_job_id"])
PY
)"
export FAILED_JOB_ID QUEUED_JOB_ID

log "validating queue job listing"
curl_json GET /queue/jobs >"${SMOKE_TMP_DIR}/queue-worker-jobs.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads((Path(os.environ["SMOKE_TMP_DIR_PY"]) / "queue-worker-jobs.json").read_text())
ids = {job["queue_job_id"] for job in payload.get("jobs", [])}
required = {os.environ["FAILED_JOB_ID"], os.environ["QUEUED_JOB_ID"]}
if not required.issubset(ids):
    raise SystemExit(f"expected jobs missing from /queue/jobs: {required - ids}")
PY

log "retrying failed queue job"
curl_json POST "/queue/jobs/${FAILED_JOB_ID}/retry" '{"reason":"queue_worker_smoke_retry","publish":false}' >"${SMOKE_TMP_DIR}/queue-worker-retry.json"

log "cancelling queued queue job"
curl_json POST "/queue/jobs/${QUEUED_JOB_ID}/cancel" '{"reason":"queue_worker_smoke_cancel"}' >"${SMOKE_TMP_DIR}/queue-worker-cancel.json"

log "checking queue stats and worker payload shape"
curl_json GET /queue/stats >"${SMOKE_TMP_DIR}/queue-worker-stats-after.json"
"${VENV_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

tmp = Path(os.environ["SMOKE_TMP_DIR_PY"])
retry_payload = json.loads((tmp / "queue-worker-retry.json").read_text())
cancel_payload = json.loads((tmp / "queue-worker-cancel.json").read_text())
stats_payload = json.loads((tmp / "queue-worker-stats-after.json").read_text())
workers_payload = json.loads((tmp / "queue-worker-workers.json").read_text())

if retry_payload.get("job", {}).get("status") != "queued":
    raise SystemExit(f"retry endpoint did not requeue job: {retry_payload}")
if cancel_payload.get("job", {}).get("status") != "cancelled":
    raise SystemExit(f"cancel endpoint did not cancel job: {cancel_payload}")

stats = stats_payload.get("stats", {})
if "queued" not in stats or "cancelled" not in stats or "total" not in stats:
    raise SystemExit(f"queue stats payload missing expected keys: {stats_payload}")

workers = workers_payload.get("workers", [])
for worker in workers:
    required_keys = {"worker_id", "status", "last_heartbeat_at", "stale", "claimed_jobs_count"}
    missing = required_keys - set(worker)
    if missing:
        raise SystemExit(f"worker payload missing keys {missing}: {worker}")
print("queue worker smoke ok")
PY

log "cleaning up smoke rows"
"${VENV_PYTHON}" - <<'PY'
import os

import psycopg

url = os.environ["AP_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg", "")
with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("delete from queue_jobs where id in (%s, %s)", (os.environ["FAILED_JOB_ID"], os.environ["QUEUED_JOB_ID"]))
    conn.commit()
PY

log "queue worker smoke ok"
