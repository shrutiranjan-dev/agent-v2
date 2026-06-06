#!/usr/bin/env bash
set -euo pipefail

OWNER="shrutiranjan-dev"
REPO="agent-v2"
SHA=""
TIMEOUT_SECONDS=600
POLL_SECONDS=15
REQUIRE_WORKFLOWS=("CI" "Repo Hygiene")

usage() {
  cat <<'USAGE'
usage: check-github-actions.sh [--owner OWNER] [--repo REPO] [--sha SHA] [--timeout-seconds N] [--poll-seconds N] [--require-workflows "CI,Repo Hygiene"]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift ;;
    --repo) REPO="$2"; shift ;;
    --sha) SHA="$2"; shift ;;
    --timeout-seconds) TIMEOUT_SECONDS="$2"; shift ;;
    --poll-seconds) POLL_SECONDS="$2"; shift ;;
    --require-workflows)
      IFS=',' read -r -a REQUIRE_WORKFLOWS <<<"$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[check-github-actions] FAIL: unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -z "${SHA}" ]]; then
  SHA="$(git rev-parse HEAD)"
fi

for i in "${!REQUIRE_WORKFLOWS[@]}"; do
  REQUIRE_WORKFLOWS[$i]="$(printf '%s' "${REQUIRE_WORKFLOWS[$i]}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
done

log() { printf '[check-github-actions] %s\n' "$*"; }
fail() { printf '[check-github-actions] FAIL: %s\n' "$*" >&2; exit 1; }

fetch_payload() {
  if command -v gh >/dev/null 2>&1; then
    METHOD="gh"
    gh api "/repos/${OWNER}/${REPO}/actions/runs?head_sha=${SHA}&per_page=100"
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    fail "Neither gh nor curl is available."
  fi

  METHOD="rest"
  local auth_header=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth_header=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl -fsSL \
    -H "Accept: application/vnd.github+json" \
    -H "User-Agent: agent-v2-ci-verifier" \
    "${auth_header[@]}" \
    "https://api.github.com/repos/${OWNER}/${REPO}/actions/runs?head_sha=${SHA}&per_page=100"
}

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  fail "python3 or python is required to parse the GitHub API response."
fi
PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
METHOD=""

while [[ $(date +%s) -lt ${deadline} ]]; do
  if ! payload="$(fetch_payload)"; then
    fail "Unable to query GitHub Actions. Install gh or allow GitHub REST API access."
  fi

  python_output="$(
    printf '%s' "${payload}" | "${PYTHON_BIN}" - "${REQUIRE_WORKFLOWS[@]}" <<'PY'
import json
import sys

payload = json.load(sys.stdin)
required = sys.argv[1:]
runs = payload.get("workflow_runs") or []
by_name = {}
for run in runs:
    name = run.get("name")
    if not name:
        continue
    current = by_name.get(name)
    if current is None or (run.get("created_at") or "") > (current.get("created_at") or ""):
        by_name[name] = run

missing = []
pending = []
failed = []
selected = []
for name in required:
    run = by_name.get(name)
    if run is None:
        missing.append(name)
        continue
    selected.append(run)
    status = run.get("status") or ""
    conclusion = run.get("conclusion")
    print(f"WORKFLOW\t{run.get('name')}\t{status}\t{conclusion or 'null'}\t{run.get('html_url') or ''}")
    if status == "completed" and conclusion != "success":
        failed.append(f"{name}={conclusion}")
    elif status != "completed" or conclusion != "success":
        pending.append(name)

if missing:
    print("MISSING\t" + ",".join(missing))
if pending:
    print("PENDING\t" + ",".join(pending))
if failed:
    print("FAILED\t" + ",".join(failed))
if not missing and not pending and not failed:
    print("RESULT\tsuccess")
PY
  )"

  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    if [[ "${line}" == WORKFLOW$'\t'* ]]; then
      IFS=$'\t' read -r _ name status conclusion url <<<"${line}"
      printf 'WORKFLOW name=%s status=%s conclusion=%s url=%s\n' "${name}" "${status}" "${conclusion}" "${url}"
    elif [[ "${line}" == RESULT$'\t'success ]]; then
      log "method=${METHOD}"
      log "all required workflows succeeded"
      exit 0
    elif [[ "${line}" == FAILED$'\t'* ]]; then
      fail "Required workflows failed: ${line#FAILED$'\t'}"
    elif [[ "${line}" == MISSING$'\t'* ]]; then
      missing="${line#MISSING$'\t'}"
    elif [[ "${line}" == PENDING$'\t'* ]]; then
      pending="${line#PENDING$'\t'}"
    fi
  done <<<"${python_output}"

  if [[ -n "${missing:-}" ]]; then
    log "waiting for workflows to appear: ${missing}"
  elif [[ -n "${pending:-}" ]]; then
    log "waiting for workflows to complete: ${pending}"
  fi
  missing=""
  pending=""
  sleep "${POLL_SECONDS}"
done

fail "Timed out waiting for required workflows to complete successfully."
