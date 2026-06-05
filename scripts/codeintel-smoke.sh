#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
SMOKE_WORKSPACE_PATH="${CODEINTEL_SMOKE_WORKSPACE_PATH:-backend/app/codeintel}"
DB_URL_SOURCE="unset"
if [[ -n "${AP_TEST_POSTGRES_URL:-}" ]]; then
  DB_URL_SOURCE="AP_TEST_POSTGRES_URL"
elif [[ -n "${AP_DATABASE_URL:-}" ]]; then
  DB_URL_SOURCE="AP_DATABASE_URL"
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for code intelligence smoke." >&2
  exit 2
fi

echo "codeintel smoke: backend=${API_BASE}"
echo "codeintel smoke: db_url_source=${DB_URL_SOURCE}"
echo "codeintel smoke: workspace_path=${SMOKE_WORKSPACE_PATH}"

curl -fsS "${API_BASE}/health" >/dev/null
health_status="$(
  curl -sS -o /tmp/codeintel-health.json -w '%{http_code}' "${API_BASE}/health/codeintel"
)"
if [[ "${health_status}" == "404" ]]; then
  echo "stale backend: ${API_BASE}/health/codeintel returned 404. Rebuild/restart backend before running this smoke." >&2
  cat /tmp/codeintel-health.json >&2 || true
  exit 1
fi
if [[ "${health_status}" != "200" ]]; then
  echo "codeintel health failed with HTTP ${health_status}" >&2
  cat /tmp/codeintel-health.json >&2 || true
  exit 1
fi

curl -fsS \
  --max-time 120 \
  -H "content-type: application/json" \
  -d "{\"workspace_path\":\"${SMOKE_WORKSPACE_PATH}\",\"force\":true}" \
  "${API_BASE}/code/index" >/tmp/codeintel-index.json

python3 - <<'PY'
import json

with open("/tmp/codeintel-index.json", encoding="utf-8") as handle:
    data = json.load(handle)
if data.get("files_indexed", 0) + data.get("files_skipped", 0) <= 0:
    raise SystemExit(f"code index did not process any files: {data}")
print("code index:", data)
PY

curl -fsS "${API_BASE}/code/map?depth=2&include_symbols=true" >/tmp/codeintel-map.json
curl -fsS "${API_BASE}/code/symbols?limit=20" >/tmp/codeintel-symbols.json
curl -fsS "${API_BASE}/code/diagnostics?limit=20" >/tmp/codeintel-diagnostics.json

python3 - <<'PY'
import json

with open("/tmp/codeintel-map.json", encoding="utf-8") as handle:
    data = json.load(handle)["code_map"]
if data.get("file_count", 0) <= 0:
    raise SystemExit(f"code map has no files: {data}")
print("code map:", {"files": data.get("file_count"), "symbols": data.get("symbol_count"), "languages": data.get("languages")})
PY

status="$(
  curl -sS -o /tmp/codeintel-outside.json -w '%{http_code}' \
    -H "content-type: application/json" \
    -d '{"workspace_path":"../","force":false}' \
    "${API_BASE}/code/index"
)"
if [[ "${status}" != "403" ]]; then
  echo "expected outside workspace index attempt to return 403, got ${status}" >&2
  cat /tmp/codeintel-outside.json >&2 || true
  exit 1
fi

echo "codeintel smoke ok"
