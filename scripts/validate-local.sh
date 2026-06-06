#!/usr/bin/env bash
# Local validation script for the agent-v2 repo.
#
# Usage:
#   bash scripts/validate-local.sh                # default: compile, ruff, pytest, frontend, docker config, CLI/TUI smoke
#   bash scripts/validate-local.sh --with-docker  # additionally check docker compose services
#   bash scripts/validate-local.sh --with-smokes  # additionally run available Bash smokes
#   bash scripts/validate-local.sh --skip-frontend
#   bash scripts/validate-local.sh --skip-tests
#   bash scripts/validate-local.sh --base-url http://localhost:8000
set -euo pipefail

WITH_DOCKER=0
WITH_SMOKES=0
SKIP_FRONTEND=0
SKIP_TESTS=0
BASE_URL="${AP_BASE_URL:-http://localhost:8000}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-docker) WITH_DOCKER=1 ;;
    --with-smokes) WITH_SMOKES=1 ;;
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    --base-url) BASE_URL="$2"; shift ;;
    --base-url=*) BASE_URL="${1#--base-url=}" ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

PYTHON_BIN="python3"
if [[ "$(uname -s)" != "Linux" && -x ".venv/Scripts/python.exe" ]]; then
  PYTHON_BIN=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

export AP_BASE_URL="${BASE_URL}"
export AP_CLI_BASE_URL="${BASE_URL}"
export AP_CLI_WS_URL="$(echo "${BASE_URL}" | sed -E 's|^http|ws|')"
export AP_CLI_TIMEOUT_SECONDS="30"
export AP_BACKEND_URL="${BASE_URL}"

log() { printf '[validate-local] %s\n' "$*"; }
fail() { printf '[validate-local] FAIL: %s\n' "$*" >&2; exit 1; }

log "compileall backend/app"
${PYTHON_BIN} -m compileall -q backend/app

log "ruff check backend/app backend/tests"
${PYTHON_BIN} -m ruff check backend/app backend/tests

if [[ "${SKIP_TESTS}" -eq 0 ]]; then
  log "pytest backend/tests"
  tmp_dir="$(pwd)/.tmp/pytest"
  mkdir -p "${tmp_dir}"
  TMP="${tmp_dir}" TEMP="${tmp_dir}" ${PYTHON_BIN} -m pytest backend/tests
fi

if [[ "${SKIP_FRONTEND}" -eq 0 ]]; then
  log "npm run build (frontend)"
  (cd frontend && npm run build)
fi

if command -v docker >/dev/null 2>&1; then
  log "docker compose config"
  docker compose config >/dev/null
else
  log "SKIP: docker not on PATH; skipping docker compose config"
fi

log "CLI/TUI smoke (scripts/cli-tui-smoke.ps1) - requires PowerShell"
if command -v powershell >/dev/null 2>&1; then
  powershell -ExecutionPolicy Bypass -File scripts/cli-tui-smoke.ps1
else
  log "SKIP: powershell not on PATH; skipping CLI/TUI smoke. Run scripts/cli-tui-smoke.ps1 on Windows."
fi

if [[ "${WITH_DOCKER}" -eq 1 ]]; then
  if command -v docker >/dev/null 2>&1; then
    log "WithDocker: docker compose ps"
    docker compose ps
    log "WithDocker: docker compose config backend backend-worker"
    docker compose config backend backend-worker >/dev/null
  else
    log "SKIP: docker not on PATH"
  fi
else
  log "WithDocker not requested; skipping docker service checks"
fi

if [[ "${WITH_SMOKES}" -eq 1 ]]; then
  log "WithSmokes: running available Bash smokes"
  for smoke in db-migration-smoke.sh codeintel-smoke.sh lsp-smoke.sh mcp-plugin-smoke.sh real-mcp-smoke.sh permission-resume-smoke.sh observability-smoke.sh; do
    if [[ -f "scripts/${smoke}" ]]; then
      log "running ${smoke}"
      bash "scripts/${smoke}"
    else
      log "SKIP: ${smoke} not found"
    fi
  done
else
  log "WithSmokes not requested; pass --with-smokes to run available Bash smokes"
fi

log "ok"
