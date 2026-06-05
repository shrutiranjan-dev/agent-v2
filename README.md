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
docker compose up --build
scripts/migrate.sh
scripts/pull-ollama-models.sh
```

Backend: http://localhost:8000

Frontend: http://localhost:5173

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
