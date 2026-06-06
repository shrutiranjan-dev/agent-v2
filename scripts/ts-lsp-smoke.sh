#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="ts-lsp-smoke"

log() { echo "[$SCRIPT_NAME] $*"; }

fail() { echo "::error::$*" >&2; echo "TS_LSP=failed"; echo "TS_LSP_REASON=$*"; exit 2; }

BASE_URL="${AP_BASE_URL:-${API_BASE:-${AP_BACKEND_URL:-http://localhost:8000}}}"
BASE_URL="${BASE_URL%/}"
WORKSPACE_PATH="${TS_LSP_SMOKE_WORKSPACE_PATH:-frontend/src}"
LSP_FILE="${TS_LSP_SMOKE_FILE:-frontend/src/App.tsx}"
STRICT="${STRICT_REAL_TS_LSP:-0}"
SKIP_MISSING=0
REAL_MODE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --real) REAL_MODE=1; STRICT=1 ;;
        --skip-if-missing) SKIP_MISSING=1 ;;
        -u|--base-url) BASE_URL="$2"; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE_TMP="${SMOKE_TMP_DIR:-$REPO_ROOT/.tmp/smokes}"
mkdir -p "$SMOKE_TMP"

log "checking backend health at $BASE_URL"
HEALTH=$(curl -fsS "$BASE_URL/health")
if [[ -z "$HEALTH" ]]; then
    fail "backend health check returned empty response"
fi

if [[ "$REAL_MODE" -eq 1 ]]; then
    log "real-mode: verifying node and typescript-language-server availability"

    if ! command -v node &>/dev/null; then
        if [[ "$SKIP_MISSING" -eq 1 ]]; then
            echo "TS_LSP=skipped_ts_server_missing"
            log "ts-lsp smoke ok (skipped: node not found)"
            exit 0
        fi
        fail "--real mode requires 'node' on PATH"
    fi
    log "node version: $(node --version)"

    if ! command -v npm &>/dev/null; then
        if [[ "$SKIP_MISSING" -eq 1 ]]; then
            echo "TS_LSP=skipped_ts_server_missing"
            log "ts-lsp smoke ok (skipped: npm not found)"
            exit 0
        fi
        fail "--real mode requires 'npm' on PATH"
    fi
    log "npm version: $(npm --version)"

    TSLS_BIN="$REPO_ROOT/frontend/node_modules/.bin/typescript-language-server"
    if [[ ! -x "$TSLS_BIN" ]]; then
        if [[ "$SKIP_MISSING" -eq 1 ]]; then
            echo "TS_LSP=skipped_ts_server_missing"
            log "ts-lsp smoke ok (skipped: typescript-language-server not found at $TSLS_BIN)"
            exit 0
        fi
        fail "--real mode requires typescript-language-server in frontend/node_modules"
    fi
    log "typescript-language-server found at $TSLS_BIN"
    echo "TS_LSP=checking"
fi

log "fetching /health/codeintel"
LSP_HEALTH=$(curl -fsS "$BASE_URL/health/codeintel")
echo "$LSP_HEALTH" > "$SMOKE_TMP/ts-lsp-health.json"

TS_SERVER=$(echo "$LSP_HEALTH" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ts=d.get('lsp_servers',{}).get('typescript') or d.get('lsp_servers',{}).get('typescriptreact')
print(json.dumps(ts or {}))
" 2>/dev/null || echo "{}")

TS_ENABLED=$(echo "$TS_SERVER" | python3 -c "import json,sys;print(json.load(sys.stdin).get('enabled',False))")
TS_MODE=$(echo "$TS_SERVER" | python3 -c "import json,sys;print(json.load(sys.stdin).get('mode',''))")
log "ts lsp server status: mode=$TS_MODE enabled=$TS_ENABLED"

if [[ "$REAL_MODE" -eq 1 ]]; then
    TS_REAL=$(echo "$TS_SERVER" | python3 -c "import json,sys;print(json.load(sys.stdin).get('real_lsp_enabled',False))")
    if [[ "$TS_REAL" != "True" ]]; then
        fail "TS_LSP real mode but typescript LSP is not active"
    fi
fi

log "checking symbols for $LSP_FILE"
SYM_RESP=$(curl -fsS "$BASE_URL/code/symbols?file=$(python3 -c "import urllib.parse;print(urllib.parse.quote('$LSP_FILE'))")&limit=50")
echo "$SYM_RESP" > "$SMOKE_TMP/ts-lsp-symbols.json"

SYM_SOURCE=$(echo "$SYM_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('source',''))")
SYM_LSP_SERVER=$(echo "$SYM_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('lsp_server',''))")
SYM_LANG=$(echo "$SYM_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('language',''))")

log "lsp symbols: source=$SYM_SOURCE language=$SYM_LANG lsp_server=$SYM_LSP_SERVER"

if [[ "$REAL_MODE" -eq 1 ]]; then
    if [[ "$SYM_SOURCE" != "real_lsp" ]]; then
        SYM_REASON=$(echo "$SYM_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('fallback_reason',''))")
        fail "TS_LSP real mode but /code/symbols source != real_lsp (source=$SYM_SOURCE reason=$SYM_REASON)"
    fi
    if [[ "$SYM_LSP_SERVER" != "typescript" && "$SYM_LSP_SERVER" != "typescriptreact" && "$SYM_LSP_SERVER" != "javascript" && "$SYM_LSP_SERVER" != "javascriptreact" ]]; then
        fail "TS_LSP real mode but lsp_server is not a TS/JS language (got $SYM_LSP_SERVER)"
    fi
    echo "TS_LSP=passed"
else
    echo "TS_LSP=disabled_static_fallback"
fi

log "ts-lsp smoke ok"
