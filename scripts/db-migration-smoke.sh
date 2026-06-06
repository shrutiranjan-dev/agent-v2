#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${AP_TEST_POSTGRES_URL:-${AP_DATABASE_URL:-}}"
VENV_PYTHON=".venv/bin/python"
VENV_ALEMBIC=".venv/bin/alembic"

if [[ "$(uname -s)" != "Linux" && -x ".venv/Scripts/python.exe" ]]; then
  VENV_PYTHON=".venv/Scripts/python.exe"
fi
if [[ "$(uname -s)" != "Linux" && -x ".venv/Scripts/alembic.exe" ]]; then
  VENV_ALEMBIC=".venv/Scripts/alembic.exe"
fi
if [[ ! -x "${VENV_PYTHON}" ]]; then
  VENV_PYTHON="python"
fi
if [[ ! -x "${VENV_ALEMBIC}" ]]; then
  VENV_ALEMBIC="${VENV_PYTHON} -m alembic"
fi

if [[ -z "${DATABASE_URL}" ]]; then
  echo "AP_TEST_POSTGRES_URL or AP_DATABASE_URL must point at a real PostgreSQL database." >&2
  exit 2
fi

export AP_DATABASE_URL="${DATABASE_URL}"

${VENV_ALEMBIC} -c backend/alembic.ini upgrade head

"${VENV_PYTHON}" - <<'PY'
import os

import psycopg

url = os.environ["AP_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg", "")
required = {
    "organizations",
    "sessions",
    "messages",
    "agent_runs",
    "tool_calls",
    "permission_requests",
    "human_input_requests",
    "session_summaries",
    "memory_items",
    "queue_jobs",
    "code_files",
    "code_symbols",
    "code_references",
    "code_diagnostics",
    "system_events",
    "model_calls",
}
with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("select table_name from information_schema.tables where table_schema = 'public'")
        tables = {row[0] for row in cur.fetchall()}
        missing = sorted(required - tables)
        if missing:
            raise SystemExit(f"Missing migration tables: {missing}")
        cur.execute("select extname from pg_extension where extname = 'vector'")
        if cur.fetchone() is None:
            raise SystemExit("pgvector extension is not installed")
print("migration smoke ok")
PY
