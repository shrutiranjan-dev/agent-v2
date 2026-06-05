#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
SMOKE_WORKSPACE_PATH="${CODEINTEL_SMOKE_WORKSPACE_PATH:-backend/app/codeintel}"
DB_URL_SOURCE="unset"
PYTHON_BIN="python3"
SMOKE_TMP_DIR="${SMOKE_TMP_DIR:-$(pwd)/.tmp/smokes}"
mkdir -p "${SMOKE_TMP_DIR}"
if command -v cygpath >/dev/null 2>&1; then
  SMOKE_TMP_DIR_PY="$(cygpath -w "${SMOKE_TMP_DIR}")"
else
  SMOKE_TMP_DIR_PY="${SMOKE_TMP_DIR}"
fi
export SMOKE_TMP_DIR SMOKE_TMP_DIR_PY

if [[ -x ".venv/Scripts/python.exe" ]]; then
  PYTHON_BIN=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi
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
  curl -sS -o "${SMOKE_TMP_DIR}/codeintel-health.json" -w '%{http_code}' "${API_BASE}/health/codeintel"
)"
if [[ "${health_status}" == "404" ]]; then
  echo "stale backend: ${API_BASE}/health/codeintel returned 404. Rebuild/restart backend before running this smoke." >&2
  cat "${SMOKE_TMP_DIR}/codeintel-health.json" >&2 || true
  exit 1
fi
if [[ "${health_status}" != "200" ]]; then
  echo "codeintel health failed with HTTP ${health_status}" >&2
  cat "${SMOKE_TMP_DIR}/codeintel-health.json" >&2 || true
  exit 1
fi

curl -fsS \
  --max-time 120 \
  -H "content-type: application/json" \
  -d "{\"workspace_path\":\"${SMOKE_WORKSPACE_PATH}\",\"force\":true}" \
  "${API_BASE}/code/index" >"${SMOKE_TMP_DIR}/codeintel-index.json"

"${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
with (tmp_dir / "codeintel-index.json").open(encoding="utf-8") as handle:
    data = json.load(handle)
if data.get("files_indexed", 0) + data.get("files_skipped", 0) <= 0:
    raise SystemExit(f"code index did not process any files: {data}")
print("code index:", data)
PY

curl -fsS "${API_BASE}/code/map?depth=2&include_symbols=true" >"${SMOKE_TMP_DIR}/codeintel-map.json"
curl -fsS "${API_BASE}/code/symbols?limit=20" >"${SMOKE_TMP_DIR}/codeintel-symbols.json"
curl -fsS "${API_BASE}/code/diagnostics?limit=20" >"${SMOKE_TMP_DIR}/codeintel-diagnostics.json"

"${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
with (tmp_dir / "codeintel-map.json").open(encoding="utf-8") as handle:
    data = json.load(handle)["code_map"]
if data.get("file_count", 0) <= 0:
    raise SystemExit(f"code map has no files: {data}")
print("code map:", {"files": data.get("file_count"), "symbols": data.get("symbol_count"), "languages": data.get("languages")})
PY

status="$(
  curl -sS -o "${SMOKE_TMP_DIR}/codeintel-outside.json" -w '%{http_code}' \
    -H "content-type: application/json" \
    -d '{"workspace_path":"../","force":false}' \
    "${API_BASE}/code/index"
)"
if [[ "${status}" != "403" ]]; then
  echo "expected outside workspace index attempt to return 403, got ${status}" >&2
  cat "${SMOKE_TMP_DIR}/codeintel-outside.json" >&2 || true
  exit 1
fi

echo "codeintel smoke ok"
