#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="file-change-smoke"

log() { echo "[${SCRIPT_NAME}] $1"; }
fail_smoke() {
  echo "[${SCRIPT_NAME}] FAIL: $1" >&2
  echo "FILE_CHANGES=failed"
  echo "FILE_CHANGES_REASON=$1"
  exit 2
}

BASE_URL="${AP_BASE_URL:-${API_BASE:-${AP_BACKEND_URL:-http://localhost:8000}}}"
BASE_URL="${BASE_URL%/}"

log "checking backend health at $BASE_URL"
HEALTH=$(curl -fsS "${BASE_URL}/health")
if ! echo "$HEALTH" | grep -q '"status":"ok"'; then
  fail_smoke "backend health did not return status=ok"
fi

log "validating /file-changes route registration"
OPENAPI=$(curl -fsS "${BASE_URL}/openapi.json")
LIST_PATH=$(echo "$OPENAPI" | python3 -c "import json,sys; data=json.load(sys.stdin); print('/file-changes' if '/file-changes' in data['paths'] else '')")
DETAIL_PATH=$(echo "$OPENAPI" | python3 -c "import json,sys; data=json.load(sys.stdin); matches=[p for p in data['paths'] if p.startswith('/file-changes/') and p.count('/')==2]; print(matches[0] if matches else '')")
REVERT_PATH=$(echo "$OPENAPI" | python3 -c "import json,sys; data=json.load(sys.stdin); matches=[p for p in data['paths'] if p.startswith('/file-changes/') and p.endswith('/revert')]; print(matches[0] if matches else '')")

if [ -z "$LIST_PATH" ]; then
  fail_smoke "/file-changes list path missing"
fi
if [ -z "$DETAIL_PATH" ]; then
  fail_smoke "/file-changes/{id} detail path missing"
fi
if [ -z "$REVERT_PATH" ]; then
  fail_smoke "/file-changes/{id}/revert path missing"
fi
log "registered: $LIST_PATH $DETAIL_PATH $REVERT_PATH"

log "exercising GET /file-changes (metadata-only)"
LIST_STATUS=$(curl -s -o /tmp/file-changes-list.json -w "%{http_code}" "${BASE_URL}/file-changes?limit=1")
if [ "$LIST_STATUS" != "200" ]; then
  fail_smoke "GET /file-changes returned status $LIST_STATUS"
fi
python3 -c "import json; data=json.load(open('/tmp/file-changes-list.json')); assert 'file_changes' in data, 'missing file_changes'; assert 'count' in data, 'missing count'; print('list ok count=' + str(data['count']))"

log "exercising GET /file-changes/{id} with unknown id (expect 404)"
UNKNOWN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/file-changes/00000000-0000-0000-0000-000000000000")
if [ "$UNKNOWN_STATUS" != "404" ]; then
  fail_smoke "GET /file-changes/{unknown} expected 404 got $UNKNOWN_STATUS"
fi

log "exercising POST /file-changes/{id}/revert with unknown id (expect 404)"
REVERT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{"force":false}' "${BASE_URL}/file-changes/00000000-0000-0000-0000-000000000000/revert")
if [ "$REVERT_STATUS" != "404" ]; then
  fail_smoke "POST /file-changes/{unknown}/revert expected 404 got $REVERT_STATUS"
fi

echo "FILE_CHANGES=endpoint_validated"
log "file-change smoke ok"
