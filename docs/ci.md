# CI and Smoke Automation

Default GitHub Actions require no repository secrets, no cloud model provider, and no local Ollama model.

## Local Source Of Truth vs CI Compatibility Gate

This repository has two complementary validation lanes, and they are not
the same thing:

- **Local source of truth: Windows PowerShell.** The primary local shell is
  Windows PowerShell 5.1+. `scripts/validate-local.ps1` is the canonical
  "is local validation green?" command on a developer workstation, and the
  PowerShell smokes (`cli-tui-smoke.ps1`, `codeintel-smoke.ps1`,
  `db-migration-smoke.ps1`, `lsp-smoke.ps1`, `observability-smoke.ps1`,
  `queue-worker-smoke.ps1`) are the canonical local smoke surface. The
  Windows-first policy is documented in
  [`docs/windows-shell-policy.md`](windows-shell-policy.md) and the Codex
  terminal conventions are in
  [`docs/codex-windows-execution.md`](codex-windows-execution.md).
- **CI compatibility gate: GitHub Actions on `ubuntu-latest`.** The Linux
  pipeline exists to prove the project still builds, tests, lints, migrates,
  and runs the real `pylsp` smoke on a clean Ubuntu runner. It is a
  compatibility check, not the primary development loop. Workflows must
  not be removed even if local Windows validation is already green; the CI
  gate is what protects the repo from regressions that only show up on a
  fresh Linux container.

The two lanes are intentionally separate:

- A green local `validate-local.ps1 -WithSmokes` run does **not** flip
  parity status to `REAL_LSP_CI_VALIDATED`; that label requires the
  `check-github-actions.ps1` verifier to confirm that the `CI` and
  `Repo Hygiene` workflows both concluded `success` on the public GitHub
  Actions API. See `scripts/mark-ci-validated.ps1` for the guarded doc
  update.
- A green CI run does **not** replace local validation. CI is a clean-room
  compatibility gate; local Windows is where product decisions are made.
- A Bash-only smoke (`mcp-plugin-smoke.sh`, `real-mcp-smoke.sh`,
  `permission-resume-smoke.sh`) that requires Git Bash, WSL, or system
  Bash must not be a hard CI dependency for a Windows-first primary
  validation pass. The PowerShell wrappers print "Bash optional" and exit
  `0` on the skip path; `validate-local.ps1 -WithSmokes` classifies those
  as `skipped`, not `failed`, so the overall pass count stays truthful.

## Workflows

- `CI` runs on pull requests and pushes to `main`. It validates backend compile, Ruff, backend tests, frontend build, Docker Compose config, migrations against real pgvector Postgres, deterministic API smokes, a dedicated real Python LSP smoke against a live backend, and a dedicated CLI/TUI headless smoke.
- `Repo Hygiene` runs on pull requests and pushes to `main`. It blocks committed `.env` files, private keys, runtime folders, ignored artifact source packages, invalid flow parity JSON (matrix + verified variants), shell syntax errors, CRLF in shell scripts, PowerShell parse errors, missing `pyproject.toml`, and broken line-ending policy.
- `Manual Smoke` runs only through `workflow_dispatch`. It builds the Docker Compose stack and runs the heavier smoke suite against live containers.

## Repo-Local CI Verification

Use the repo-local verifier before changing docs from `REAL_LSP_CI_VALIDATED` to `REAL_LSP_CI_VALIDATED`.

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-github-actions.ps1 -Owner shrutiranjan-dev -Repo agent-v2 -Sha (git rev-parse HEAD) -RequireWorkflows "CI","Repo Hygiene"
```

Guarded doc update:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\mark-ci-validated.ps1
```

The guard refuses to edit docs unless all required workflows conclude `success`.

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

The real Python LSP path is also valid on local Windows: running
`scripts/lsp-smoke.ps1 -Real` against a locally running backend with
`AP_LSP_ENABLED=true AP_LSP_PYTHON_COMMAND=pylsp` produces the same
`REAL_LSP=passed` gate locally. Local Windows validation is sufficient to
label the path `REAL_LSP_VALIDATED` in this repo's parity docs. The
`REAL_LSP_CI_VALIDATED` label is a **stricter** claim that additionally
requires the `check-github-actions.ps1` verifier to confirm a green `CI`
workflow on the public GitHub Actions API; it remains a separate gate
because the CI is a clean-room compatibility check, not a substitute for
local Windows validation.

## Real TypeScript LSP CI Job

The `real-typescript-lsp-smoke` job in `.github/workflows/ci.yml` is mandatory in default CI.

Status: `TS_LSP_CI_JOB_ADDED_PENDING_REMOTE_VALIDATION`

It:

1. Installs backend dependencies with `pip install -e ".[test]"`.
2. Installs frontend dependencies with `npm ci --prefix frontend` (which includes `typescript` and `typescript-language-server` devDependencies).
3. Applies migrations against a real `pgvector/pgvector:pg16` Postgres service.
4. Starts the backend on the runner with `AP_TS_LSP_ENABLED=true` and `AP_TS_LSP_COMMAND=./frontend/node_modules/.bin/typescript-language-server --stdio`.
5. Runs `bash scripts/ts-lsp-smoke.sh --real --base-url http://localhost:8000`.
6. Requires `TS_LSP=passed` in the smoke log.
7. Uploads the smoke log, backend log, and response dumps from `/tmp/ts-lsp-smoke/` on failure with 7 day retention.

This job is the CI proof for the real TypeScript/JS LSP path. It does not require Ollama generation and does not pass if the runtime falls back to `static_fallback`.

The real TypeScript LSP path is also valid on local Windows: running
`scripts/ts-lsp-smoke.ps1 -Real` against a locally running backend with
`AP_TS_LSP_ENABLED=true` and `AP_TS_LSP_COMMAND=.\frontend\node_modules\.bin\typescript-language-server.cmd --stdio`
produces the same `TS_LSP=passed` gate locally. The
`TS_LSP_CI_VALIDATED` label is a **stricter** claim that additionally
requires the `check-github-actions.ps1` verifier to confirm a green `CI`
workflow on the public GitHub Actions API.

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
- `real-ts-lsp-smoke-logs` from the `Real TypeScript LSP Smoke` job (`ts-lsp-smoke` output, backend log, and response dumps).
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

## Smoke Result Semantics

The PowerShell smokes and `validate-local.ps1` use a standardised four-state
result protocol so the validator can be truthful about which checks ran,
which were skipped, which degraded, and which failed.

Each smoke prints one of:

```text
SMOKE_RESULT=passed
SMOKE_RESULT=failed
SMOKE_RESULT=skipped
SMOKE_RESULT=warned
```

Optionally:

```text
SMOKE_REASON=<short reason>
SMOKE_CATEGORY=required|optional
```

`validate-local.ps1` parses these markers (and falls back to exit code when
the marker is absent). The final summary is always:

```text
summary: passed=X failed=Y skipped=Z warned=W
```

Exit behaviour:

- `failed > 0` of a **required** step -> exit non-zero.
- `failed > 0` of an **optional** step -> log a WARN line, do not exit 1.
- `skipped` -> optional check could not run because a prerequisite is
  missing; never increments `failed` and never exits non-zero by default.
- `warned` -> optional check ran and found a degraded / non-blocking
  condition; never exits non-zero.
- `-RequireOptionalSmokes` converts optional `SKIP` and `FAIL` -> a
  required-step `FAIL` so the user can opt into stricter handling. By
  default the script still exits 0 when only optional smokes are
  promoted; with `-RequireOptionalSmokes` any promoted optional failure
  makes the script exit non-zero. `WARN` results are never promoted.

Required Windows smokes (must pass on every run):

- `cli-tui-smoke.ps1` (also required in default `validate-local.ps1`)
- `db-migration-smoke.ps1` when Docker Postgres is up
- `codeintel-smoke.ps1` when the backend is up
- `lsp-smoke.ps1` (static fallback path; the strict real-pylsp path is the
  dedicated CI job, not a Windows local required step)

Optional Windows smokes (skip cleanly when prerequisites are missing):

- `observability-smoke.ps1`
- `queue-worker-smoke.ps1` (WARN if all workers are stale but Docker
  backend-worker is healthy; SKIP if Docker is not available)
- `mcp-plugin-smoke.ps1` (SKIP when `MCP_REAL_SERVER` is not configured or
  the plugin system reports degraded; full plugin / MCP flow needs Bash)
- `real-mcp-smoke.ps1` (SKIP if MCP SDK is missing; full flow needs Bash)
- `permission-resume-smoke.ps1` (SKIP unless `AP_ENABLE_TEST_ENDPOINTS=true`,
  an Ollama model is available, and active worker heartbeats exist; the
  full e2e flow needs Bash)

Why some smokes skip without `AP_ENABLE_TEST_ENDPOINTS=true`:

- The `permission-resume` and `human-input` deterministic flows bypass
  Ollama rate limits and randomness to make the test deterministic. They
  are not safe in production or in any environment where the backend
  might be exposed to real user input, so they are gated by the same
  `AP_ENABLE_TEST_ENDPOINTS` flag that the in-process test endpoints use.

How to enable optional smokes intentionally:

- `AP_ENABLE_TEST_ENDPOINTS=true docker compose up -d --build backend` then
  `powershell -ExecutionPolicy Bypass -File scripts\permission-resume-smoke.ps1`
  to run the full permission resume e2e flow.
- `MCP_REAL_SERVER=<stdio-spec> powershell -ExecutionPolicy Bypass -File
  scripts\mcp-plugin-smoke.ps1` to opt into the full MCP plugin flow
  (still needs Bash on Windows for the actual plugin load test).
- `powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1
  -WithSmokes -RequireOptionalSmokes` to promote every optional `SKIP` and
  `FAIL` to a required `FAIL`, exit non-zero if any promotion happened,
  and see which optional checks the local environment cannot run.
