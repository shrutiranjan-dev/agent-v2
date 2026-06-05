# Local Agent Platform

A Python local-first multi-agent runtime inspired by architectural patterns studied from OpenCode, implemented as an independent product with its own Python backend, React dashboard, PostgreSQL-first data model, and local Ollama-only provider layer.

This project is not affiliated with OpenCode and does not reuse OpenCode branding or package identity. The OpenCode source clone is kept under `external/opencode-source` only for architecture study.

## Stack

- Python 3.12, FastAPI, Pydantic v2
- SQLAlchemy 2.0 async, asyncpg, Alembic
- PostgreSQL with pgvector, Redis, Qdrant, Neo4j, MinIO, ClickHouse
- Local Ollama API only
- React, TypeScript, Vite
- WebSocket session event streaming

## Quick Start

```bash
cp .env.example .env
docker compose up -d --build
scripts/migrate.sh
scripts/pull-ollama-models.sh
```

Backend: http://localhost:8000

Frontend: http://localhost:5173

## Windows Setup

The repository is intended to be portable between Linux and Windows. Shell scripts stay in `scripts/*.sh` for Linux, WSL, Git Bash, and CI. On Windows PowerShell, use the equivalent commands below.

Install prerequisites:

- Docker Desktop for Windows with the Linux container engine enabled
- Git for Windows
- Python 3.12
- Node.js 20 or newer
- Ollama for Windows

Clone and configure:

```powershell
git clone git@github.com:shrutiranjan-dev/agent-v2.git
cd agent-v2
Copy-Item .env.example .env
```

Pull local Ollama models from PowerShell:

```powershell
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
ollama pull llama3.1:8b
```

Start the Docker services from PowerShell:

```powershell
docker compose up -d --build
```

Run migrations from PowerShell:

```powershell
docker compose run --rm backend alembic -c backend/alembic.ini upgrade head
```

Run backend checks locally from PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest backend/tests
```

Run frontend checks locally from PowerShell:

```powershell
cd frontend
npm install
npm run build
```

Optional smoke checks from PowerShell can run through Git Bash or WSL. If you run them from a shell that supports Bash, set the Docker PostgreSQL URL first:

```powershell
$env:AP_TEST_POSTGRES_URL="postgresql+psycopg://agent:agent@localhost:15432/agent_platform"
```

Then use Git Bash or WSL:

```bash
scripts/runtime-smoke.sh
scripts/codeintel-smoke.sh
scripts/real-mcp-smoke.sh
```

Windows notes:

- Keep your real `.env` local. It is ignored by Git.
- Docker Desktop exposes host Ollama to containers through `host.docker.internal`, which is already the default `AP_OLLAMA_BASE_URL`.
- `.gitattributes` keeps shell scripts with LF endings and PowerShell scripts with CRLF endings.

## Developer Commands

```bash
scripts/dev-up.sh
scripts/migrate.sh
scripts/smoke-test.sh
```

Local Python checks:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest
```

Frontend checks:

```bash
cd frontend
npm install
npm run build
```

## Docker Services

Default Docker Compose services:

- `backend`: FastAPI API and WebSocket server
- `backend-worker`: queue-backed agent/permission/human-input worker
- `frontend`: React/Vite dashboard
- `postgres`: PostgreSQL with pgvector
- `redis`: queue, locks, and pub/sub coordination
- `qdrant`: semantic memory backend
- `neo4j`: graph memory backend
- `minio`: artifact/object storage
- `clickhouse`: analytics/event observability

Optional profile:

- `ollama`: Docker Ollama service, disabled by default. The normal setup uses host Ollama at `http://host.docker.internal:11434`.

Start all default services:

```bash
docker compose up -d --build
```

Stop services:

```bash
docker compose down
```

## Architecture Notes

The architecture study is under `docs/opencode-study/` and records the source commit inspected:

```text
f6197cefe1745eef29ea6afae26be5a56c7a79ee
```

## Runtime Protocol

Local models are asked to return strict JSON:

```json
{"type":"final","content":"..."}
```

or:

```json
{"type":"tool_call","tool":"read.file","input":{"path":"/workspace/README.md"}}
```

Invalid JSON is repaired once. Repeated identical tool calls from the same agent are blocked on the third attempt and logged as a system event.

## Initial Boundaries

Implemented now:

- Native agents: build, plan, general, explore, summary, compaction
- Native typed tools
- Permission ask/allow/deny flow
- Tool audit logging
- Agent run history
- Ollama model list/pull/generate integration
- Dependency health checks
- React dashboard

Deferred intentionally:

- Dynamic plugin execution
- MCP runtime execution
- Multi-node run ownership
- Full context epoch and compaction policy
