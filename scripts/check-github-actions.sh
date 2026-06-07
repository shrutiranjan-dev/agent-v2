#!/usr/bin/env bash
#
# check-github-actions.sh — Bash mirror of scripts/check-github-actions.ps1.
#
# This script is a thin correct mirror. The PowerShell version is the
# source of truth for this verifier and is exercised on every Windows
# release. The Bash version exists so that:
#   1. Linux/macOS developers can run the same check locally.
#   2. CI smoke jobs on Linux runners can use the same semantics.
#
# PowerShell-only features (the deterministic state machine,
# exponential backoff on transient REST errors, and the in-script
# self-test) are not duplicated here. The Bash version uses the same
# SHA-pinned selection logic, the same WORKFLOW table format, and the
# same exit-code contract (0 on success, 1 on failure/timeout).
#
# Usage:
#   bash scripts/check-github-actions.sh [--owner OWNER] [--repo REPO]
#       [--sha SHA] [--timeout-seconds N] [--poll-seconds N]
#       [--require-workflows "CI,Repo Hygiene"] [--once]
#
# Exit codes:
#   0  all required workflows concluded success for the exact SHA
#   1  a required workflow is missing, failed, cancelled, timed out,
#      or the timeout elapsed
#   2  bad arguments or required tool (python3/curl) missing

set -euo pipefail

OWNER="shrutiranjan-dev"
REPO="agent-v2"
SHA=""
TIMEOUT_SECONDS=600
POLL_SECONDS=15
REQUIRE_WORKFLOWS=("CI" "Repo Hygiene")
ONCE=0

usage() {
  cat <<'USAGE'
usage: check-github-actions.sh [--owner OWNER] [--repo REPO] [--sha SHA]
                              [--timeout-seconds N] [--poll-seconds N]
                              [--require-workflows "CI,Repo Hygiene"]
                              [--once]
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
      shift ;;
    --once) ONCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[check-github-actions] FAIL: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# Trim and validate the SHA: must be 7-64 hex chars, lower-cased.
if [[ -z "${SHA}" ]]; then
  SHA="$(git rev-parse HEAD 2>/dev/null || true)"
fi
SHA="$(printf '%s' "${SHA}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
if [[ ! "${SHA}" =~ ^[0-9a-f]{7,64}$ ]]; then
  echo "[check-github-actions] FAIL: invalid or missing -Sha (got: '${SHA}')." >&2
  exit 2
fi

for i in "${!REQUIRE_WORKFLOWS[@]}"; do
  REQUIRE_WORKFLOWS[$i]="$(printf '%s' "${REQUIRE_WORKFLOWS[$i]}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
done

log()  { printf '[check-github-actions] %s\n' "$*"; }
fail() { printf '[check-github-actions] FAIL: %s\n' "$*" >&2; exit 1; }

# Pick a transport.
if command -v gh >/dev/null 2>&1; then
  METHOD="gh"
  log "transport=gh"
else
  METHOD="rest"
  log "transport=rest (gh CLI not available)"
fi

# python3 is required to parse the response reliably.
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  fail "python3 or python is required to parse the GitHub API response."
fi

fetch_payload() {
  if [[ "${METHOD}" == "gh" ]]; then
    gh api "/repos/${OWNER}/${REPO}/actions/runs?head_sha=${SHA}&per_page=100"
    return 0
  fi
  if ! command -v curl >/dev/null 2>&1; then
    fail "Neither gh nor curl is available."
  fi
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

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
poll_index=0
last_selected=""

log "owner=${OWNER} repo=${REPO} sha=${SHA} required=$(IFS=, ; echo "${REQUIRE_WORKFLOWS[*]}") timeout=${TIMEOUT_SECONDS}s once=${ONCE}"

while :; do
  poll_index=$(( poll_index + 1 ))
  now=$(date +%s)
  if [[ "${now}" -ge "${deadline}" ]]; then break; fi

  if ! payload="$(fetch_payload 2>/dev/null)"; then
    if [[ "${METHOD}" == "gh" ]]; then
      log "gh lookup failed; falling back to GitHub REST API"
      METHOD="rest"
      continue
    fi
    log "transport error (will retry): curl/gh exit non-zero"
    sleep "${POLL_SECONDS}"
    continue
  fi

  python_output="$(
    printf '%s' "${payload}" | "${PYTHON_BIN}" - "${SHA}" "${REQUIRE_WORKFLOWS[@]}" <<'PY'
import json
import sys

requested_sha = sys.argv[1].lower()
required = sys.argv[2:]
payload = json.load(sys.stdin)

# Rate-limit detection (some transports return 200 with a body).
msg = payload.get("message") if isinstance(payload, dict) else None
if isinstance(msg, str) and "rate limit" in msg.lower():
    print("RATE_LIMIT\t" + msg)
    sys.exit(0)

runs = (payload.get("workflow_runs") or [])
# Defense in depth: filter to the exact requested SHA even if the API
# ever returns runs for other SHAs.
matching = [r for r in runs if (r.get("head_sha") or "").lower() == requested_sha]

selected = []
for name in required:
    candidates = [r for r in matching if r.get("name") == name]
    if not candidates:
        continue
    completed = [r for r in candidates if r.get("status") == "completed"]
    if completed:
        # Newest completed run wins, by updated_at then run_number.
        completed.sort(key=lambda r: (r.get("updated_at") or "", r.get("run_number") or 0), reverse=True)
        selected.append(completed[0])
    else:
        candidates.sort(key=lambda r: (r.get("created_at") or "", r.get("run_number") or 0), reverse=True)
        selected.append(candidates[0])

# Print per-selected-run diagnostics in the same format as the PowerShell verifier.
for r in selected:
    name = r.get("name") or ""
    rid = r.get("id") or 0
    rsha = (r.get("head_sha") or "").lower()
    status = r.get("status") or ""
    conclusion = r.get("conclusion") or "null"
    created = r.get("created_at") or ""
    updated = r.get("updated_at") or ""
    url = r.get("html_url") or ""
    print(f"WORKFLOW\t{name}\t{rid}\t{rsha}\t{status}\t{conclusion}\t{created}\t{updated}\t{url}")

missing = [n for n in required if n not in {r.get("name") for r in selected}]
failed = []
pending = []
for r in selected:
    status = r.get("status") or ""
    conclusion = r.get("conclusion")
    if status == "completed" and conclusion != "success":
        failed.append(f"{r.get('name')}={conclusion} (run {r.get('id')})")
    elif status != "completed" or conclusion != "success":
        pending.append(f"{r.get('name')}={status}/{conclusion or 'null'}")

if missing:
    print("MISSING\t" + ",".join(missing))
if failed:
    print("FAILED\t" + "; ".join(failed))
if pending:
    print("PENDING\t" + "; ".join(pending))
if not missing and not failed and not pending:
    print("RESULT\tsuccess")
PY
  )"

  state_line=""
  missing_line=""
  failed_line=""
  pending_line=""
  workflow_lines=()

  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    case "${line}" in
      WORKFLOW*)  workflow_lines+=("${line#WORKFLOW	}") ;;
      RESULT*)    state_line="${line#RESULT	}" ;;
      MISSING*)   missing_line="${line#MISSING	}" ;;
      FAILED*)    failed_line="${line#FAILED	}" ;;
      PENDING*)   pending_line="${line#PENDING	}" ;;
      RATE_LIMIT*) fail "GitHub REST API rate limit exceeded. Set GITHUB_TOKEN and re-run. (${line#RATE_LIMIT	})" ;;
    esac
  done <<<"${python_output}"

  for row in "${workflow_lines[@]:-}"; do
    [[ -z "${row}" ]] && continue
    IFS=$'\t' read -r name rid rsha status conclusion created updated url <<<"${row}"
    printf '[check-github-actions] WORKFLOW name=%s run=%s sha=%s status=%s conclusion=%s created=%s updated=%s url=%s\n' \
      "${name}" "${rid}" "${rsha}" "${status}" "${conclusion}" "${created}" "${updated}" "${url}"
  done

  if [[ -n "${failed_line}" ]]; then
    fail "Required workflows failed for SHA ${SHA}: ${failed_line}"
  fi
  if [[ -n "${missing_line}" ]]; then
    discovered="$(printf '%s' "${workflow_lines[@]:-}" | awk -F'\t' '{print $1}' | sort -u | paste -sd ',' -)"
    [[ -z "${discovered}" ]] && discovered="(none yet for SHA)"
    log "poll ${poll_index} state=waiting_for_required_workflows missing=[${missing_line}] discovered=[${discovered}]"
    last_selected="${workflow_lines[*]:-}"
  elif [[ -n "${pending_line}" ]]; then
    log "poll ${poll_index} state=waiting_for_completion pending=[${pending_line}]"
    last_selected="${workflow_lines[*]:-}"
  elif [[ "${state_line}" == "success" ]]; then
    log "poll ${poll_index} state=success"
    log "all required workflows concluded success for SHA ${SHA}"
    exit 0
  fi

  if [[ "${ONCE}" == "1" ]]; then break; fi

  remaining=$(( deadline - $(date +%s) ))
  if [[ "${remaining}" -le 0 ]]; then break; fi
  sleep_for="${POLL_SECONDS}"
  if [[ "${sleep_for}" -gt "${remaining}" ]]; then sleep_for="${remaining}"; fi
  if [[ "${sleep_for}" -le 0 ]]; then break; fi
  sleep "${sleep_for}"
done

# Loop exited without success: classify the reason.
if [[ -n "${last_selected}" ]] || [[ "${ONCE}" == "1" ]]; then
  if [[ -n "${missing_line}" ]]; then
    fail "Timed out after ${TIMEOUT_SECONDS}s waiting for required workflows to appear for SHA ${SHA}: ${missing_line}"
  fi
  if [[ -n "${pending_line}" ]]; then
    fail "Timed out after ${TIMEOUT_SECONDS}s waiting for required workflows to complete for SHA ${SHA}: ${pending_line}"
  fi
fi
fail "Timed out after ${TIMEOUT_SECONDS}s waiting for required workflows to complete successfully for SHA ${SHA}."
