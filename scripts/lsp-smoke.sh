#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
LSP_SMOKE_WORKSPACE_PATH="${LSP_SMOKE_WORKSPACE_PATH:-backend/app/codeintel}"
LSP_SMOKE_FILE="${LSP_SMOKE_FILE:-backend/app/codeintel/lsp_client.py}"
STRICT_REAL_LSP="${STRICT_REAL_LSP:-0}"
PYTHON_BIN="python3"
SMOKE_TMP_DIR="${SMOKE_TMP_DIR:-$(pwd)/.tmp/smokes}"
mkdir -p "${SMOKE_TMP_DIR}"
if command -v cygpath >/dev/null 2>&1; then
  SMOKE_TMP_DIR_PY="$(cygpath -w "${SMOKE_TMP_DIR}")"
else
  SMOKE_TMP_DIR_PY="${SMOKE_TMP_DIR}"
fi
export SMOKE_TMP_DIR SMOKE_TMP_DIR_PY LSP_SMOKE_FILE STRICT_REAL_LSP

if [[ -x ".venv/Scripts/python.exe" ]]; then
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
from pathlib import Path

tmp_dir = Path(os.environ["SMOKE_TMP_DIR_PY"])
symbols = json.loads((tmp_dir / "lsp-symbols.json").read_text(encoding="utf-8")).get("symbols") or []
if not symbols:
    raise SystemExit("LSP smoke did not return any symbols for the target file.")
print("lsp symbols:", {"count": len(symbols), "first": symbols[0].get("name")})
diagnostics = json.loads((tmp_dir / "lsp-diagnostics.json").read_text(encoding="utf-8")).get("diagnostics") or []
print("lsp diagnostics:", {"count": len(diagnostics)})
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
payload = json.loads((tmp_dir / "lsp-definition.json").read_text(encoding="utf-8"))
definition = payload.get("definition")
if not definition:
    raise SystemExit(f"LSP smoke could not resolve a definition: {payload}")
print("lsp definition:", {"name": definition.get("name"), "file_path": definition.get("file_path"), "start_line": definition.get("start_line")})
PY

echo "lsp smoke ok"
