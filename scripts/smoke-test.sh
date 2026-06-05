#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:8000}"

curl -fsS "$API/health" | grep -q '"status":"ok"'
curl -fsS "$API/health/dependencies" >/tmp/agent-platform-deps.json
curl -fsS "$API/agents" | grep -q '"build"'
curl -fsS "$API/tools" | grep -q '"read.file"'

SESSION_ID="$(
  curl -fsS -X POST "$API/sessions" \
    -H 'content-type: application/json' \
    -d '{"title":"Smoke test","agent_id":"build"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["session"]["id"])'
)"

curl -fsS "$API/sessions/$SESSION_ID" | grep -q "$SESSION_ID"

set +e
curl -fsS -X POST "$API/sessions/$SESSION_ID/messages" \
  -H 'content-type: application/json' \
  -d '{"content":"Return exactly {\"type\":\"final\",\"content\":\"smoke ok\"}"}' >/tmp/agent-platform-message.json
MESSAGE_STATUS=$?
set -e
if [ "$MESSAGE_STATUS" -ne 0 ]; then
  echo "Message endpoint reached but model call failed. Check Ollama model availability." >&2
fi

curl -fsS "$API/permissions" >/tmp/agent-platform-permissions.json

echo "Smoke test completed for session $SESSION_ID"

