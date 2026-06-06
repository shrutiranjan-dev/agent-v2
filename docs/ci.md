# CI and Smoke Automation

Default GitHub Actions require no repository secrets, no cloud model provider, and no local Ollama model.

## Workflows

- `CI` runs on pull requests and pushes to `main`. It validates backend compile, Ruff, backend tests, frontend build, Docker Compose config, migrations against real pgvector Postgres, deterministic API smokes, a dedicated real Python LSP smoke against a live backend, and a dedicated CLI/TUI headless smoke.
- `Repo Hygiene` runs on pull requests and pushes to `main`. It blocks committed `.env` files, private keys, runtime folders, ignored artifact source packages, invalid flow parity JSON (matrix + verified variants), shell syntax errors, CRLF in shell scripts, PowerShell parse errors, missing `pyproject.toml`, and broken line-ending policy.
- `Manual Smoke` runs only through `workflow_dispatch`. It builds the Docker Compose stack and runs the heavier smoke suite against live containers.

## Default CI Design

The fast CI path starts a real `pgvector/pgvector:pg16` Postgres service for migration and API smoke validation. It starts the FastAPI backend directly on the runner with CI-safe environment values:

- `AP_ENABLE_TEST_ENDPOINTS=true` only inside CI smoke jobs.
- `AP_OLLAMA_BASE_URL=http://127.0.0.1:9` so no Ollama model call can accidentally happen.
- Redis pub/sub and queue execution are disabled for host-side smokes.
- Qdrant embeddings are disabled.

The deterministic smoke scripts are:

- `scripts/codeintel-smoke.sh`
- `scripts/lsp-smoke.sh` in static fallback mode (`REAL_LSP=disabled_static_fallback`)
- `scripts/lsp-smoke.sh --real` in strict real mode for the dedicated `real-python-lsp-smoke` CI job
- `scripts/mcp-plugin-smoke.sh`
- `scripts/observability-smoke.sh`
- `scripts/cli-tui-smoke.ps1` (also run as a dedicated CI job)
- `python -m backend.app.cli.main tui --check` (headless smoke)

Human-input, memory-compaction, and model-generation smokes are not part of default CI because they need explicit non-production test endpoints or model/runtime prerequisites.

## Real Python LSP CI Job

The `real-python-lsp-smoke` job in `.github/workflows/ci.yml` is mandatory in default CI, not manual or optional.

It:

1. Installs backend dependencies with `pip install -e ".[test,codeintel]"`.
2. Verifies `python -c "import pylsp"` before doing smoke work.
3. Applies migrations against a real `pgvector/pgvector:pg16` Postgres service.
4. Starts the backend on the runner with `AP_LSP_ENABLED=true` and `AP_LSP_PYTHON_COMMAND=pylsp`.
5. Runs `bash scripts/lsp-smoke.sh --real --base-url http://localhost:8000`.
6. Requires `REAL_LSP=passed` in the smoke log.
7. Uploads the smoke log, backend log, and response dumps from `/tmp/lsp-smoke/` on failure with 7 day retention.

This job is the CI proof for the already validated real Python LSP path. It does not require Ollama generation and does not pass if the runtime falls back to `static_fallback`.

## CLI/TUI CI Job

The dedicated `cli-tui-smoke` job in `.github/workflows/ci.yml`:

1. Installs backend dependencies from `pip install -e ".[test]"` (this picks up `textual` from `pyproject.toml`).
2. Verifies CLI imports and Textual widget composition without launching a terminal.
3. Verifies `tui --help` advertises the new `--check` flag.
4. Applies migrations to a `pgvector/pgvector:pg16` service.
5. Starts the FastAPI backend on port 8000 with `AP_ENABLE_TEST_ENDPOINTS=true` and `AP_OLLAMA_BASE_URL=http://127.0.0.1:9`.
6. Runs `python -m backend.app.cli.main tui --check` against the live backend. Exit 0 is required.
7. Uploads the backend log as an artifact (`cli-tui-smoke-backend-log`, 7 day retention) on failure.

The job fails fast on missing imports, missing `--check` flag, or backend connectivity issues, without requiring a TTY, Ollama model generation, or interactive input.

## CI Failure Artifacts

CI jobs upload failure artifacts (7 day retention) to the Actions run page:

- `backend-pytest-log` from the `Backend` job (pytest output and JUnit XML).
- `migration-smoke-log` from the `Migration Smoke` job (alembic + validation log).
- `safe-smokes-backend-log` from the `Safe API Smokes` job (uvicorn log).
- `cli-tui-smoke-backend-log` from the new `CLI/TUI Smoke` job.
- `real-python-lsp-smoke-logs` from the `Real Python LSP Smoke` job (`lsp-smoke` output, backend log, and response dumps).
- `repo-hygiene-log` from the `Repo Hygiene` job (parity JSON validation output).
- `manual-smoke-docker-logs` from the `Manual Smoke` workflow (always uploaded, not just on failure).

No secrets are uploaded. Only stdout/stderr and the JSON validation output are captured.

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

The single-command validator runs compile/ruff/pytest/frontend build/docker config/CLI/TUI smoke:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1
```

Useful flags:

```powershell
# Add docker service health checks
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -WithDocker

# Add all available PowerShell-native smokes (observability, queue-worker, codeintel, lsp, db-migration, mcp-plugin, real-mcp, permission-resume)
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -WithSmokes

# Override the backend URL (default http://localhost:8000)
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -BaseUrl http://localhost:8000

# Skip frontend build or backend tests
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -SkipFrontend
powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -SkipTests
```

Run backend checks manually:

```powershell
.\.venv\Scripts\python -m compileall backend\app
.\.venv\Scripts\python -m ruff check backend\app backend\tests
New-Item -ItemType Directory -Force .tmp\pytest | Out-Null
$tmp=(Resolve-Path .tmp\pytest).Path
$env:TEMP=$tmp
$env:TMP=$tmp
.\.venv\Scripts\python -m pytest backend\tests
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

Run PowerShell-native smokes (no Bash required):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\codeintel-smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts\lsp-smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts\observability-smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts\queue-worker-smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts\db-migration-smoke.ps1
```

Use Git Bash or WSL for Bash-only smoke scripts:

```bash
AP_TEST_POSTGRES_URL='postgresql+psycopg://agent:agent@localhost:15432/agent_platform' bash scripts/db-migration-smoke.sh
bash scripts/codeintel-smoke.sh
bash scripts/lsp-smoke.sh
bash scripts/mcp-plugin-smoke.sh
bash scripts/observability-smoke.sh
bash scripts/real-mcp-smoke.sh
bash scripts/permission-resume-smoke.sh
```

The PowerShell wrappers for `mcp-plugin-smoke`, `real-mcp-smoke`, and `permission-resume-smoke` will automatically use Git Bash, WSL, or the system Bash if any of them is installed; otherwise they skip with a clear message instead of faking a pass.

The Bash `validate-local.sh` script mirrors the PowerShell version for Linux/macOS developers:

```bash
bash scripts/validate-local.sh
bash scripts/validate-local.sh --with-docker
bash scripts/validate-local.sh --with-smokes
bash scripts/validate-local.sh --base-url http://localhost:8000
bash scripts/validate-local.sh --skip-frontend --skip-tests
```

## Known Limitations

- Human-input and memory-compaction smokes are skipped by design when `AP_ENABLE_TEST_ENDPOINTS=false`.
- Ollama model generation is never required in default CI. The CI sets `AP_OLLAMA_BASE_URL=http://127.0.0.1:9` so any accidental model call fails fast instead of silently succeeding against a missing local model.
- Static-fallback LSP still remains the default behavior for the general `safe-smokes` job. The dedicated `real-python-lsp-smoke` job is the strict gate for the live `pylsp` path. The smoke prints `REAL_LSP=passed` only after `pylsp` is importable and at least one `/code/...` response body reports `source: real_lsp`.
- The dedicated `cli-tui-smoke` CI job starts a real backend and runs `tui --check`. It does not launch the full Textual app (which requires a TTY); that path is covered by `AgentPlatformTuiApp` instantiation in the import check step and by the local `cli-tui-smoke.ps1` script.
