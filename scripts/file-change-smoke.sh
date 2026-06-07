#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="file-change-smoke"

log() { echo "[${SCRIPT_NAME}] $1"; }
fail_smoke() {
  echo "[${SCRIPT_NAME}] FAIL: $1" >&2
  echo "FILE_CHANGES=failed"
  echo "FILE_CHANGES_REASON=$1"
  echo "SMOKE_RESULT=failed"
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
BATCH_PATH=$(echo "$OPENAPI" | python3 -c "import json,sys; data=json.load(sys.stdin); print('/file-changes/revert-batch' if '/file-changes/revert-batch' in data['paths'] else '')")

if [ -z "$LIST_PATH" ]; then
  fail_smoke "/file-changes list path missing"
fi
if [ -z "$DETAIL_PATH" ]; then
  fail_smoke "/file-changes/{id} detail path missing"
fi
if [ -z "$REVERT_PATH" ]; then
  fail_smoke "/file-changes/{id}/revert path missing"
fi
if [ -z "$BATCH_PATH" ]; then
  fail_smoke "/file-changes/revert-batch path missing"
fi
log "registered: $LIST_PATH $DETAIL_PATH $REVERT_PATH $BATCH_PATH"

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

if [ "${AP_ENABLE_TEST_ENDPOINTS:-false}" != "true" ]; then
  log "test endpoints disabled (set AP_ENABLE_TEST_ENDPOINTS=true to enable full smoke)"
  echo "FILE_CHANGES=skipped_test_endpoint_disabled"
  echo "SMOKE_RESULT=skipped"
  exit 0
fi

TEST_PATH=$(echo "$OPENAPI" | python3 -c "import json,sys; data=json.load(sys.stdin); print('/test-endpoints/file-change-write' if '/test-endpoints/file-change-write' in data['paths'] else '')")
if [ -z "$TEST_PATH" ]; then
  fail_smoke "test-endpoints not registered despite AP_ENABLE_TEST_ENDPOINTS=true"
fi
log "running real end-to-end file-change smoke"

STAMP=$(date -u +%Y%m%d%H%M%S%N)
REL_PATH="smoke/file-change-smoke-${STAMP}.txt"
ORIGINAL="original-${STAMP}"
MODIFIED="modified-${STAMP}"
WS_ROOT="${AP_WORKSPACE_ROOT:-/workspace}"

WRITE_BODY=$(python3 -c "import json; print(json.dumps({'path':'$REL_PATH','content':'$MODIFIED','before_content':'$ORIGINAL','tool_name':'write.file'}))")
WRITE_STATUS=$(curl -s -o /tmp/file-changes-write.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$WRITE_BODY" "${BASE_URL}/test-endpoints/file-change-write")
if [ "$WRITE_STATUS" != "200" ]; then
  fail_smoke "test write endpoint returned status $WRITE_STATUS"
fi
CHANGE_ID=$(python3 -c "import json; print(json.load(open('/tmp/file-changes-write.json'))['file_change_id'])")
log "captured file_change_id=$CHANGE_ID for $REL_PATH"

LIST2_STATUS=$(curl -s -o /tmp/file-changes-list2.json -w "%{http_code}" "${BASE_URL}/file-changes?limit=200")
if [ "$LIST2_STATUS" != "200" ]; then
  fail_smoke "GET /file-changes returned status $LIST2_STATUS"
fi
FOUND=$(python3 -c "import json; data=json.load(open('/tmp/file-changes-list2.json')); m=[r for r in data['file_changes'] if r['id']=='$CHANGE_ID']; print(len(m))")
if [ "$FOUND" != "1" ]; then
  fail_smoke "captured change_id $CHANGE_ID not visible in /file-changes listing"
fi
REVERT_STATUS=$(python3 -c "import json; data=json.load(open('/tmp/file-changes-list2.json')); m=[r for r in data['file_changes'] if r['id']=='$CHANGE_ID'][0]; print(m['revert_status'], m['revertible'])")
if [ "$REVERT_STATUS" != "not_reverted True" ]; then
  fail_smoke "expected revert_status=not_reverted revertible=true, got '$REVERT_STATUS'"
fi
log "list ok: change visible revertible=true revert_status=not_reverted"

DETAIL_STATUS=$(curl -s -o /tmp/file-changes-detail.json -w "%{http_code}" "${BASE_URL}/file-changes/${CHANGE_ID}?include_content=true")
if [ "$DETAIL_STATUS" != "200" ]; then
  fail_smoke "GET /file-changes/${CHANGE_ID} returned status $DETAIL_STATUS"
fi
python3 -c "import json; data=json.load(open('/tmp/file-changes-detail.json')); diff=data['file_change'].get('diff') or ''; assert '$MODIFIED' in diff, 'expected diff to contain modified content'; print('detail ok')"

ON_DISK_PATH="${WS_ROOT}/${REL_PATH}"
if [ ! -f "$ON_DISK_PATH" ]; then
  fail_smoke "on-disk file not found at $ON_DISK_PATH"
fi
ACTUAL=$(cat "$ON_DISK_PATH")
if [ "$ACTUAL" != "$MODIFIED" ]; then
  fail_smoke "on-disk file content does not match modified; got '$ACTUAL' expected '$MODIFIED'"
fi
log "on-disk file matches modified content"

REVERT_BODY='{"force":false}'
REVERT_STATUS=$(curl -s -o /tmp/file-changes-revert.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$REVERT_BODY" "${BASE_URL}/file-changes/${CHANGE_ID}/revert")
if [ "$REVERT_STATUS" = "202" ] && [ "${AP_FILE_CHANGE_REVERT_REQUIRES_APPROVAL:-true}" != "false" ]; then
  PERMISSION_ID=$(python3 -c "import json; data=json.load(open('/tmp/file-changes-revert.json')); print(data['detail']['permission_request_id'])")
  log "revert waiting_permission: permission_request_id=$PERMISSION_ID"
  APPROVE_BODY='{"message":"smoke_approval"}'
  APPROVE_STATUS=$(curl -s -o /tmp/file-changes-approve.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$APPROVE_BODY" "${BASE_URL}/permissions/${PERMISSION_ID}/approve")
  if [ "$APPROVE_STATUS" != "200" ]; then
    fail_smoke "permission approve returned status $APPROVE_STATUS"
  fi
  log "permission approved"
  REVERT_BODY=$(python3 -c "import json; print(json.dumps({'force':False,'permission_request_id':'$PERMISSION_ID'}))")
  REVERT_STATUS=$(curl -s -o /tmp/file-changes-revert.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$REVERT_BODY" "${BASE_URL}/file-changes/${CHANGE_ID}/revert")
fi
if [ "$REVERT_STATUS" != "200" ]; then
  fail_smoke "POST /file-changes/${CHANGE_ID}/revert returned status $REVERT_STATUS"
fi
python3 -c "import json; data=json.load(open('/tmp/file-changes-revert.json')); assert data['file_change']['revert_status']=='reverted', 'expected reverted, got ' + data['file_change']['revert_status']; print('revert ok restore_source=' + str(data.get('restore_source','?')))"

ACTUAL2=$(cat "$ON_DISK_PATH")
if [ "$ACTUAL2" != "$ORIGINAL" ]; then
  fail_smoke "on-disk file content was not restored; got '$ACTUAL2' expected '$ORIGINAL'"
fi
log "on-disk file restored byte-for-byte to original"

REVERT2_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$REVERT_BODY" "${BASE_URL}/file-changes/${CHANGE_ID}/revert")
if [ "$REVERT2_STATUS" != "409" ]; then
  fail_smoke "re-revert expected 409, got $REVERT2_STATUS"
fi
log "re-revert correctly returned 409 already_reverted"

echo "FILE_CHANGES=passed"
echo "SMOKE_RESULT=passed"
log "file-change e2e smoke ok"
