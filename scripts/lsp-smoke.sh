#!/usr/bin/env bash
set -euo pipefail

API_BASE="${AP_BASE_URL:-${API_BASE:-http://localhost:8000}}"
LSP_SMOKE_WORKSPACE_PATH="${LSP_SMOKE_WORKSPACE_PATH:-backend/app/codeintel}"
LSP_SMOKE_FILE="${LSP_SMOKE_FILE:-backend/app/codeintel/lsp_client.py}"
STRICT_REAL_LSP="${STRICT_REAL_LSP:-0}"
REAL_MODE=0
SKIP_REAL_IF_MISSING="${LSP_SMOKE_SKIP_IF_MISSING:-0}"
BACKEND_LOG_FILE="${BACKEND_LOG_FILE:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --real) REAL_MODE=1 ;;
    --strict-real-lsp) REAL_MODE=1 ;;
    --skip-real-if-missing) SKIP_REAL_IF_MISSING=1 ;;
    --base-url)
      shift
      if [[ $# -eq 0 ]]; then
        echo "ERROR: --base-url requires a value" >&2
        exit 2
      fi
      API_BASE="$1"
      ;;
    --base-url=*)
      API_BASE="${1#*=}"
      ;;
    --help|-h)
      cat <<USAGE
usage: lsp-smoke.sh [--real] [--skip-real-if-missing] [--base-url URL]
  Default mode: verify static fallback path; passes if /code/... returns 200.
  --real                   require AP_LSP_ENABLED=true with real pylsp available
  --skip-real-if-missing   in --real mode, skip (do not fail) if pylsp is missing
                           prints REAL_LSP=skipped_pylsp_missing and exits 0
  --base-url URL           override API base URL (or set AP_BASE_URL / API_BASE)
  --strict-real-lsp        alias for --real
USAGE
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done
if [[ "${REAL_MODE}" == "1" && "${STRICT_REAL_LSP}" != "1" ]]; then
  STRICT_REAL_LSP=1
fi
PYTHON_BIN="python3"
SMOKE_TMP_DIR="${SMOKE_TMP_DIR:-$(pwd)/.tmp/smokes}"
mkdir -p "${SMOKE_TMP_DIR}"
if command -v cygpath >/dev/null 2>&1; then
  SMOKE_TMP_DIR_PY="$(cygpath -w "${SMOKE_TMP_DIR}")"
else
  SMOKE_TMP_DIR_PY="${SMOKE_TMP_DIR}"
fi
export SMOKE_TMP_DIR SMOKE_TMP_DIR_PY LSP_SMOKE_FILE STRICT_REAL_LSP

dump_diagnostics() {
  echo "lsp smoke diagnostics:"
  if [[ -f "${SMOKE_TMP_DIR}/lsp-health.json" ]]; then
    echo "--- /health/codeintel ---"
    cat "${SMOKE_TMP_DIR}/lsp-health.json"
  fi
  if [[ -f "${SMOKE_TMP_DIR}/lsp-symbols.json" ]]; then
    echo "--- /code/symbols ---"
    cat "${SMOKE_TMP_DIR}/lsp-symbols.json"
  fi
  if [[ -f "${SMOKE_TMP_DIR}/lsp-definition.json" ]]; then
    echo "--- /code/definition ---"
    cat "${SMOKE_TMP_DIR}/lsp-definition.json"
  fi
  if [[ -f "${SMOKE_TMP_DIR}/lsp-diagnostics.json" ]]; then
    echo "--- /code/diagnostics ---"
    cat "${SMOKE_TMP_DIR}/lsp-diagnostics.json"
  fi
  if [[ -n "${BACKEND_LOG_FILE}" && -f "${BACKEND_LOG_FILE}" ]]; then
    echo "--- backend log tail ---"
    tail -n 200 "${BACKEND_LOG_FILE}" || cat "${BACKEND_LOG_FILE}"
  fi
}

trap 'status=$?; if [[ $status -ne 0 ]]; then dump_diagnostics; fi; exit $status' EXIT

if [[ "$(uname -s)" != "Linux" && -x ".venv/Scripts/python.exe" ]]; then
  PYTHON_BIN=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for LSP smoke." >&2
  exit 2
fi

echo "lsp smoke: backend=${API_BASE}"
echo "lsp smoke: workspace_path=${LSP_SMOKE_WORKSPACE_PATH}"
echo "lsp smoke: file=${LSP_SMOKE_FILE}"
echo "lsp smoke: real_mode=${REAL_MODE} skip_real_if_missing=${SKIP_REAL_IF_MISSING}"

if [[ "${REAL_MODE}" == "1" ]]; then
  if ! "${PYTHON_BIN}" -c "import pylsp" 2>/dev/null; then
    if [[ "${SKIP_REAL_IF_MISSING}" == "1" ]]; then
      echo "REAL_LSP=skipped_pylsp_missing"
      echo "lsp smoke ok (skipped: pylsp not installed)"
      exit 0
    fi
    echo "ERROR: --real mode requires 'pylsp' to be importable. Install with: pip install -e '.[codeintel]'" >&2
    exit 3
  fi
  echo "REAL_LSP=checking"
fi

curl -fsS "${API_BASE}/health" >/dev/null
curl -fsS "${API_BASE}/health/codeintel" >"${SMOKE_TMP_DIR}/lsp-health.json"

"${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
payload = json.loads((tmp_dir / "lsp-health.json").read_text(encoding="utf-8"))
lsp = payload.get("lsp") or {}
mode = lsp.get("mode")
real = bool(lsp.get("real_lsp_enabled"))
status = lsp.get("status")
if status not in {"ok", "degraded"}:
    raise SystemExit(f"unexpected LSP health status: {payload}")
if os.environ.get("STRICT_REAL_LSP") == "1" and not real:
    raise SystemExit(f"STRICT_REAL_LSP=1 but real LSP is not active: {payload}")
print("lsp health:", {"mode": mode, "real_lsp_enabled": real, "command": lsp.get("command"), "reason": lsp.get("reason")})
PY

curl -fsS \
  --max-time 120 \
  -H "content-type: application/json" \
  -d "{\"workspace_path\":\"${LSP_SMOKE_WORKSPACE_PATH}\",\"force\":true}" \
  "${API_BASE}/code/index" >"${SMOKE_TMP_DIR}/lsp-index.json"

curl -fsS "${API_BASE}/code/symbols?file=${LSP_SMOKE_FILE}&limit=50" >"${SMOKE_TMP_DIR}/lsp-symbols.json"
curl -fsS "${API_BASE}/code/diagnostics?file=${LSP_SMOKE_FILE}&limit=50" >"${SMOKE_TMP_DIR}/lsp-diagnostics.json"

"${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
strict = os.environ.get("STRICT_REAL_LSP") == "1"
payload = json.loads((tmp_dir / "lsp-symbols.json").read_text(encoding="utf-8"))
source = payload.get("source")
lsp_status = payload.get("lsp_status")
fallback_reason = payload.get("fallback_reason")
symbols = payload.get("symbols") or []
if not symbols:
    raise SystemExit("LSP smoke did not return any symbols for the target file.")
print("lsp symbols:", {"count": len(symbols), "first": symbols[0].get("name"), "source": source, "lsp_status": lsp_status})
if strict and source != "real_lsp":
    raise SystemExit(f"STRICT_REAL_LSP=1 but /code/symbols source != real_lsp: source={source} reason={fallback_reason}")
diagnostics_payload = json.loads((tmp_dir / "lsp-diagnostics.json").read_text(encoding="utf-8"))
diagnostics = diagnostics_payload.get("diagnostics") or []
print("lsp diagnostics:", {"count": len(diagnostics), "source": diagnostics_payload.get("source")})
# diagnostics can legitimately be empty when the language server reports no problems;
# only assert on /code/symbols in strict mode to keep the gate meaningful.
PY

"${PYTHON_BIN}" - >"${SMOKE_TMP_DIR}/lsp-definition-target.txt" <<'PY'
import json
import os
import urllib.parse
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
health = json.loads((tmp_dir / "lsp-health.json").read_text(encoding="utf-8"))
real = bool((health.get("lsp") or {}).get("real_lsp_enabled"))
target = Path(os.environ["LSP_SMOKE_FILE"])
query_path = urllib.parse.quote(target.as_posix(), safe="/")
if real:
    lines = target.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines, start=1):
        column = line.find("LspClient()")
        if column >= 0:
            print(f"{query_path}|{index}|{column}")
            break
    else:
        raise SystemExit("Could not find a stable LspClient() reference for real-LSP smoke.")
else:
    print(f"{query_path}|0|0")
PY

IFS='|' read -r encoded_path definition_line definition_column <"${SMOKE_TMP_DIR}/lsp-definition-target.txt"
if [[ "${definition_line}" == "0" ]]; then
  curl -fsS "${API_BASE}/code/definition?name=LspClient" >"${SMOKE_TMP_DIR}/lsp-definition.json"
else
  curl -fsS "${API_BASE}/code/definition?file=${encoded_path}&line=${definition_line}&column=${definition_column}" >"${SMOKE_TMP_DIR}/lsp-definition.json"
fi

"${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
strict = os.environ.get("STRICT_REAL_LSP") == "1"
payload = json.loads((tmp_dir / "lsp-definition.json").read_text(encoding="utf-8"))
definition = payload.get("definition")
source = payload.get("source")
if not definition:
    raise SystemExit(f"LSP smoke could not resolve a definition: {payload}")
print("lsp definition:", {"name": definition.get("name"), "file_path": definition.get("file_path"), "start_line": definition.get("start_line"), "source": source})
if strict and source != "real_lsp":
    raise SystemExit(f"STRICT_REAL_LSP=1 but /code/definition source != real_lsp: source={source}")
PY

if [[ "${REAL_MODE}" == "1" ]]; then
  echo "REAL_LSP=passed"
else
  echo "REAL_LSP=disabled_static_fallback"
fi
echo "lsp smoke ok"
