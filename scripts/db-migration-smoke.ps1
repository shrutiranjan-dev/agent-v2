param(
    [string]$DatabaseUrl = $env:AP_TEST_POSTGRES_URL
)

$ErrorActionPreference = "Stop"

$ScriptName = "db-migration-smoke"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[$ScriptName] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    Write-Error "[$ScriptName] FAIL: $Message"
    exit 2
}

if (-not $DatabaseUrl) {
    if ($env:AP_DATABASE_URL) {
        $DatabaseUrl = $env:AP_DATABASE_URL
    }
}

if (-not $DatabaseUrl) {
    Fail-Smoke "AP_TEST_POSTGRES_URL or AP_DATABASE_URL must point at a real PostgreSQL database."
}

$env:AP_DATABASE_URL = $DatabaseUrl

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Fail-Smoke "project venv python is required at $Python"
}
$Alembic = Join-Path $RepoRoot ".venv\Scripts\alembic.exe"
if (-not (Test-Path -LiteralPath $Alembic)) {
    Fail-Smoke "project venv alembic is required at $Alembic"
}

Write-SmokeLog "running alembic upgrade head"
& $Alembic -c (Join-Path $RepoRoot "backend\alembic.ini") upgrade head
if ($LASTEXITCODE -ne 0) {
    Fail-Smoke "alembic upgrade head failed with exit $LASTEXITCODE"
}

$SmokeTmpDir = if ($env:SMOKE_TMP_DIR) { $env:SMOKE_TMP_DIR } else { Join-Path $RepoRoot ".tmp\smokes" }
New-Item -ItemType Directory -Force -Path $SmokeTmpDir | Out-Null
$ValidateScript = Join-Path $SmokeTmpDir "db-migration-validate.py"
@"
import os
import sys

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
print("migration validate ok")
"@ | Set-Content -LiteralPath $ValidateScript -Encoding UTF8

Write-SmokeLog "validating required tables and pgvector extension"
& $Python $ValidateScript
if ($LASTEXITCODE -ne 0) {
    Fail-Smoke "table/extension validation failed with exit $LASTEXITCODE"
}

Write-SmokeLog "migration smoke ok"
