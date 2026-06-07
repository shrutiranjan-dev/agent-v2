#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="multi-lsp-smoke"

log() { echo "[${SCRIPT_NAME}] $1"; }
fail_smoke() {
  echo "[${SCRIPT_NAME}] FAIL: $1" >&2
  echo "MULTI_LSP=failed"
  echo "MULTI_LSP_REASON=$1"
  exit 2
}

BASE_URL="${AP_BASE_URL:-${API_BASE:-${AP_BACKEND_URL:-http://localhost:8000}}}"
BASE_URL="${BASE_URL%/}"
STRICT_REAL="${STRICT_REAL_MULTI_LSP:-0}"
REAL_GO=0
REAL_RUST=0
REAL_JAVA=0
SKIP_REAL_IF_MISSING=0
for arg in "$@"; do
  case "$arg" in
    --RealGo) REAL_GO=1 ;;
    --RealRust) REAL_RUST=1 ;;
    --RealJava) REAL_JAVA=1 ;;
    --SkipRealIfMissing) SKIP_REAL_IF_MISSING=1 ;;
  esac
done

if [ "$REAL_GO" = "1" ] || [ "$REAL_RUST" = "1" ] || [ "$REAL_JAVA" = "1" ] || [ "$STRICT_REAL" = "1" ]; then
  REAL_MODE=1
else
  REAL_MODE=0
fi

log "checking backend health at $BASE_URL"
HEALTH=$(curl -fsS "${BASE_URL}/health")
if ! echo "$HEALTH" | grep -q '"status":"ok"'; then
  fail_smoke "backend health did not return status=ok"
fi

LSP_HEALTH=$(curl -fsS "${BASE_URL}/health/codeintel")

EXPECTED_SERVERS=(python typescript go rust java clangd ruby php csharp kotlin lua)
for sid in "${EXPECTED_SERVERS[@]}"; do
  if ! echo "$LSP_HEALTH" | grep -q "\"${sid}\""; then
    fail_smoke "Missing server in /health/codeintel: $sid"
  fi
done
log "all expected servers present in /health/codeintel"

if [ "$REAL_GO" = "1" ]; then
  if command -v gopls >/dev/null 2>&1; then
    echo "GO_LSP=passed"
  elif [ "$SKIP_REAL_IF_MISSING" = "1" ]; then
    echo "GO_LSP=skipped_gopls_missing"
    log "go real-mode skipped: gopls not on PATH"
  else
    fail_smoke "--RealGo requires gopls on PATH"
  fi
fi

if [ "$REAL_RUST" = "1" ]; then
  if command -v rust-analyzer >/dev/null 2>&1; then
    echo "RUST_LSP=passed"
  elif [ "$SKIP_REAL_IF_MISSING" = "1" ]; then
    echo "RUST_LSP=skipped_rust_analyzer_missing"
    log "rust real-mode skipped: rust-analyzer not on PATH"
  else
    fail_smoke "--RealRust requires rust-analyzer on PATH"
  fi
fi

if [ "$REAL_JAVA" = "1" ]; then
  if command -v jdtls >/dev/null 2>&1; then
    echo "JAVA_LSP=passed"
  elif [ "$SKIP_REAL_IF_MISSING" = "1" ]; then
    echo "JAVA_LSP=skipped_jdtls_missing"
    log "java real-mode skipped: jdtls not on PATH"
  else
    fail_smoke "--RealJava requires jdtls on PATH"
  fi
fi

GO_SYM=$(curl -fsS "${BASE_URL}/code/symbols?file=main.go&limit=10")
if ! echo "$GO_SYM" | grep -q '"source":"static_fallback"'; then
  fail_smoke "go symbols source != static_fallback (got $GO_SYM)"
fi
if ! echo "$GO_SYM" | grep -q '"lsp_server":"none"'; then
  fail_smoke "go symbols lsp_server != none (got $GO_SYM)"
fi
if ! echo "$GO_SYM" | grep -q '"fallback_reason":"go_lsp_disabled"'; then
  fail_smoke "go symbols fallback_reason != go_lsp_disabled (got $GO_SYM)"
fi
log "go symbols ok: source=static_fallback server=none reason=go_lsp_disabled"

RUST_SYM=$(curl -fsS "${BASE_URL}/code/symbols?file=main.rs&limit=10")
if ! echo "$RUST_SYM" | grep -q '"fallback_reason":"rust_lsp_disabled"'; then
  fail_smoke "rust symbols fallback_reason != rust_lsp_disabled (got $RUST_SYM)"
fi
log "rust symbols ok: reason=rust_lsp_disabled"

if [ "$REAL_MODE" = "1" ]; then
  echo "MULTI_LSP=registry_validated_real_partial"
else
  echo "MULTI_LSP=registry_validated_static_fallback"
fi
log "multi-lsp smoke ok"
