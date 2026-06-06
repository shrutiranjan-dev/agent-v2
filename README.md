# Local Agent Platform

[![CI](https://github.com/shrutiranjan-dev/agent-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/shrutiranjan-dev/agent-v2/actions/workflows/ci.yml)
[![Repo Hygiene](https://github.com/shrutiranjan-dev/agent-v2/actions/workflows/repo-hygiene.yml/badge.svg)](https://github.com/shrutiranjan-dev/agent-v2/actions/workflows/repo-hygiene.yml)

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

Optional smoke checks from PowerShell can run through native `.ps1` scripts where available. Set the Docker PostgreSQL URL first:

```powershell
$env:AP_TEST_POSTGRES_URL="postgresql+psycopg://agent:agent@localhost:15432/agent_platform"
powershell -ExecutionPolicy Bypass -File scripts\queue-worker-smoke.ps1
```

A single `validate-local.ps1` script runs the full default validation suite (compile, ruff, pytest, frontend build, docker compose config, CLI/TUI smoke). Useful flags include `-WithDocker` to check docker service health and `-WithSmokes` to additionally run all available PowerShell-native smokes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -WithSmokes
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -SkipFrontend
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -BaseUrl http://localhost:8000
```

PowerShell-native smokes include `cli-tui-smoke.ps1`, `codeintel-smoke.ps1`, `lsp-smoke.ps1`, `observability-smoke.ps1`, `queue-worker-smoke.ps1`, and `db-migration-smoke.ps1`. The `mcp-plugin-smoke.ps1`, `real-mcp-smoke.ps1`, and `permission-resume-smoke.ps1` wrappers delegate to their Bash counterparts when Git Bash, WSL, or system Bash is available; otherwise they skip with a clear message.

A `validate-local.sh` mirror is available for Linux/macOS developers:

```bash
bash scripts/validate-local.sh
bash scripts/validate-local.sh --with-smokes
```

Other smoke checks still run through Git Bash or WSL:

```bash
scripts/runtime-smoke.sh
scripts/codeintel-smoke.sh
scripts/lsp-smoke.sh
scripts/real-mcp-smoke.sh
scripts/queue-worker-smoke.sh
```

Windows notes:

- Keep your real `.env` local. It is ignored by Git.
- Docker Desktop exposes host Ollama to containers through `host.docker.internal`, which is already the default `AP_OLLAMA_BASE_URL`.
- `.gitattributes` keeps shell scripts with LF endings and PowerShell scripts with CRLF endings.
- Host-side backend tests now degrade cleanly when `.env` points Redis at the Docker service hostname `redis`; plain `pytest backend/tests` no longer requires a separate Redis override just to run unit tests on Windows.

## Code Intelligence And LSP

Static code indexing is always available when code intelligence is enabled. Real LSP is optional and intentionally honest about its state.

Environment variables:

```bash
AP_LSP_ENABLED=false
AP_LSP_PYTHON_COMMAND=pylsp
AP_LSP_STARTUP_TIMEOUT_SECONDS=10
AP_LSP_REQUEST_TIMEOUT_SECONDS=10
AP_LSP_SHUTDOWN_TIMEOUT_SECONDS=5
AP_LSP_MAX_RESPONSE_CHARS=200000
AP_LSP_WORKSPACE_ROOT=/workspace
```

Behavior:

- When `AP_LSP_ENABLED=false`, `/health/codeintel` reports `static_fallback` and the API/tools use the indexed database fallback.
- When `AP_LSP_ENABLED=true`, the backend starts a real stdio JSON-RPC language server and uses it for file-based symbols, definitions, references, and diagnostics when the server is available.
- If the configured server is missing, times out, or fails, health reports the failure and static fallback remains available instead of pretending LSP succeeded.

Every `/code/...` response and every `code.*` tool result now carries these honesty fields so consumers can never mistake a fallback for a real-LSP result:

- `source`: `real_lsp` or `static_fallback`
- `lsp_status`: current LSP service mode (`real_lsp` / `static_fallback` / `failed`)
- `fallback_reason`: human-readable reason when the response is from fallback (or `None` for real LSP)
- `lsp`: full health snapshot including `real_lsp_enabled`, `command`, `started`, `started_at`, `request_count`, `failure_count`

Smoke options:

```bash
scripts/codeintel-smoke.sh
scripts/lsp-smoke.sh                       # static fallback smoke (default)
STRICT_REAL_LSP=1 scripts/lsp-smoke.sh    # require real pylsp + source: real_lsp
scripts/lsp-smoke.sh --real               # same as STRICT_REAL_LSP=1
scripts/lsp-smoke.sh --real --skip-real-if-missing
                                           # REAL_LSP=skipped_pylsp_missing if pylsp absent
```

Real LSP requires `python-lsp-server`:

```bash
pip install -e ".[codeintel]"   # installs pylsp
AP_LSP_ENABLED=true AP_LSP_PYTHON_COMMAND=pylsp \
  powershell -ExecutionPolicy Bypass -File scripts/lsp-smoke.ps1 -Real
```

CI now includes a dedicated mandatory `real-python-lsp-smoke` job that installs `python-lsp-server`, starts the backend with `AP_LSP_ENABLED=true`, runs `scripts/lsp-smoke.sh --real`, and only passes when the smoke prints `REAL_LSP=passed`. The repository now also ships `scripts/check-github-actions.ps1` and `scripts/mark-ci-validated.ps1` so docs only move from `REAL_LSP_CI_JOB_ADDED_PENDING_REMOTE_VALIDATION` to `REAL_LSP_CI_VALIDATED` after GitHub Actions is independently proven green. The current documented status remains `REAL_LSP_CI_JOB_ADDED_PENDING_REMOTE_VALIDATION` because the verifier could not prove a green `CI` workflow for commits `2564c64` or `ed13d13`.

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

## Terminal Coding Flow

The backend also ships a local terminal-first CLI for agent operation. It uses the existing FastAPI runtime, WebSocket session events, permission APIs, human-input APIs, queue APIs, and artifact APIs; it does not bypass `ToolExecutor` or weaken permission checks.

PowerShell examples:

```powershell
.\.venv\Scripts\python -m backend.app.cli.main health
.\.venv\Scripts\python -m backend.app.cli.main agents
.\.venv\Scripts\python -m backend.app.cli.main sessions list
.\.venv\Scripts\python -m backend.app.cli.main sessions create --title "My session" --agent build
.\.venv\Scripts\python -m backend.app.cli.main events --session <session-id>
.\.venv\Scripts\python -m backend.app.cli.main permissions --session <session-id>
.\.venv\Scripts\python -m backend.app.cli.main questions --session <session-id>
.\.venv\Scripts\python -m backend.app.cli.main diff --session <session-id>
.\.venv\Scripts\python -m backend.app.cli.main chat --session <session-id> --agent build "Implement the next safe task"
.\.venv\Scripts\python -m backend.app.cli.main queue status
.\.venv\Scripts\python -m backend.app.cli.main queue retry <job-id>
.\.venv\Scripts\python -m backend.app.cli.main queue show <job-id>
.\.venv\Scripts\python -m backend.app.cli.main artifacts list --session <session-id>
.\.venv\Scripts\python -m backend.app.cli.main tui
```

Configuration:

```powershell
$env:AP_CLI_BASE_URL="http://localhost:8000"
$env:AP_CLI_WS_URL="ws://localhost:8000"
$env:AP_CLI_TIMEOUT_SECONDS="30"
```

If installed from the package, `agentv2` is available as a console-script alias:

```powershell
agentv2 health
agentv2 tui
```

TUI (`agentv2 tui`):

The runtime TUI is a Textual full-screen application. The left column lists
sessions; the center shows the message panel above the event log; the right
column shows the tool timeline and a summary; the bottom row hosts the prompt
composer. A live WebSocket event stream feeds a pure-Python state reducer, and
modal screens cover permission, human-input, agent-switcher, and session-create
flows.

Keybindings:

```text
ctrl+c    Quit the TUI.
ctrl+n    Create a new session.
ctrl+s    Focus the session list.
ctrl+a    Open the agent switcher.
ctrl+r    Retry the latest failed queue job.
ctrl+d    Show the latest diff for the active session.
ctrl+l    Clear the message panel.
ctrl+t    Toggle the event log.
```

Headless CI smoke:

```powershell
# Exit 0 = ok, exit 2 = backend unreachable, exit 1 = app construction failed.
agentv2 tui --check
```

The deterministic smoke script avoids model-dependent generation and exercises
the new commands plus the TUI import smoke:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\cli-tui-smoke.ps1
```

## CI

GitHub Actions validate backend quality, frontend build, Docker Compose config, real Postgres migrations, deterministic non-Ollama smokes, and repo hygiene. Default CI requires no secrets and no cloud/model provider. See [docs/ci.md](docs/ci.md) for workflow details and local reproduction commands.

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
