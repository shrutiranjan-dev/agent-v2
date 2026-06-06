# CI and Smoke Automation

Default GitHub Actions require no repository secrets, no cloud model provider, and no local Ollama model.

## Workflows

- `CI` runs on pull requests and pushes to `main`. It validates backend compile, Ruff, backend tests, frontend build, Docker Compose config, migrations against real pgvector Postgres, and deterministic API smokes.
- `Repo Hygiene` runs on pull requests and pushes to `main`. It blocks committed `.env` files, private keys, runtime folders, ignored artifact source packages, invalid flow parity JSON, shell syntax errors, and broken line-ending policy.
- `Manual Smoke` runs only through `workflow_dispatch`. It builds the Docker Compose stack and runs the heavier smoke suite against live containers.

## Default CI Design

The fast CI path starts a real `pgvector/pgvector:pg16` Postgres service for migration and API smoke validation. It starts the FastAPI backend directly on the runner with CI-safe environment values:

- `AP_ENABLE_TEST_ENDPOINTS=true` only inside CI smoke jobs.
- `AP_OLLAMA_BASE_URL=http://127.0.0.1:9` so no Ollama model call can accidentally happen.
- Redis pub/sub and queue execution are disabled for host-side smokes.
- Qdrant embeddings are disabled.

The deterministic smoke scripts are:

- `scripts/codeintel-smoke.sh`
- `scripts/lsp-smoke.sh` in static fallback mode
- `scripts/mcp-plugin-smoke.sh`
- `scripts/observability-smoke.sh`

Human-input, memory-compaction, and model-generation smokes are not part of default CI because they need explicit non-production test endpoints or model/runtime prerequisites.

## Manual Docker Smoke

Use the `Manual Smoke` workflow from the GitHub Actions tab when validating the full local runtime stack. It creates `.env` from `.env.example`, enables non-production test endpoints, starts Docker Compose, waits for backend health, then runs:

- `scripts/db-migration-smoke.sh`
- `scripts/codeintel-smoke.sh`
- `scripts/lsp-smoke.sh`
- `scripts/mcp-plugin-smoke.sh`
- `scripts/observability-smoke.sh`
- `scripts/real-mcp-smoke.sh`

Docker logs are uploaded as an artifact on every manual smoke run.

## Local Reproduction on Windows

Run backend checks:

```powershell
.\.venv\Scripts\python -m compileall backend\app
.\.venv\Scripts\python -m ruff check backend\app backend\tests
New-Item -ItemType Directory -Force .tmp\pytest | Out-Null
$tmp=(Resolve-Path .tmp\pytest).Path
$env:TEMP=$tmp
$env:TMP=$tmp
.\.venv\Scripts\pytest backend\tests
```

Run frontend and Compose checks:

```powershell
npm.cmd run build --prefix frontend
docker-compose config
```

Run migration and live smoke checks after Docker services are up:

```powershell
$env:AP_TEST_POSTGRES_URL="postgresql+psycopg://agent:agent@localhost:15432/agent_platform"
docker-compose run --rm backend alembic -c backend/alembic.ini upgrade head
powershell -ExecutionPolicy Bypass -File scripts\observability-smoke.ps1
```

Use Git Bash or WSL for Bash-only smoke scripts:

```bash
AP_TEST_POSTGRES_URL='postgresql+psycopg://agent:agent@localhost:15432/agent_platform' bash scripts/db-migration-smoke.sh
bash scripts/codeintel-smoke.sh
bash scripts/lsp-smoke.sh
bash scripts/mcp-plugin-smoke.sh
bash scripts/observability-smoke.sh
```
