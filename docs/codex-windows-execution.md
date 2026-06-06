# Codex Windows Execution Guide

This guide documents the Windows PowerShell execution rules Codex must
follow when generating commands, scripts, or instructions for the
`agent-v2` repository on a Windows host. It is the operational companion
to `docs/windows-shell-policy.md`; the policy is the *what* and this guide
is the *how*.

## Project Layout On Windows

- Default working directory: `C:\Users\SHRUTI RANJAN MAJI\Desktop\my shit\agent-v2`.
  The path contains a space (`my shit`) and must always be quoted in shell
  call operators.
- Default shell: Windows PowerShell 5.1 (`$PSVersionTable.PSVersion.Major`
  is 5 on Windows 11).
- Container runtime: Docker Desktop for Windows with the Linux container
  engine enabled.
- Python: `py` shim (3.12) preferred; fall back to the explicit
  `.venv\Scripts\python.exe` for any script that the shim misroutes.
- Node: `npm.cmd` (the `.cmd` shim) is required when invoking npm from
  PowerShell to avoid the PowerShell-of-PowerShell script-block bug.
- Bash helpers: Git Bash at `C:\Program Files\Git\bin\bash.exe`. WSL is
  present at `C:\Windows\System32\wsl.exe`. The Bash-only smoke wrappers
  detect these paths automatically; if neither is present, they print
  "Bash optional" and exit `0`.

## Quoting And Path Handling

- Always quote paths with spaces. The project root is the canonical
  example.
- Use the call operator `&` with a quoted path string for executing
  scripts that have spaces in the path:

  ```powershell
  & "C:\Users\SHRUTI RANJAN MAJI\Desktop\my shit\agent-v2\scripts\validate-local.ps1" -WithSmokes
  ```

- When passing a quoted path to `Start-Process` or `Invoke-Item`, escape
  embedded quotes with backslashes or use a variable:

  ```powershell
  $script = "C:\Users\SHRUTI RANJAN MAJI\Desktop\my shit\agent-v2\scripts\validate-local.ps1"
  & $script -WithSmokes
  ```

- `Resolve-Path` returns the absolute, normalized path. Use it whenever
  Codex needs to canonicalize the project root before joining
  `backend\app`, `frontend`, or `scripts`.

- `Test-Path -LiteralPath` is required for path existence checks so that
  PowerShell does not interpret `[` and `]` in a path as a wildcard.

## Docker Compose On Windows

- Use the compose v2 plugin form: `docker compose ...` (space, not
  hyphen). It is the same binary path on Windows, Linux, and macOS, so
  commands can be copy-pasted into CI later.
- The `docker compose config` subcommand is the cheap parity check. It
  does not start any container and is safe to run on every save.
- Container names use the project directory as the prefix. The default
  compose project name for this repo is `agent-v2`, so the backend
  container is `agent-v2-backend-1`.
- For environment variables in compose, set them in the user shell with
  `$env:VAR = "value"` before invoking `docker compose`. The
  `docker-compose.yml` reads `AP_LSP_*` defaults from the host, so a
  developer can opt into the real Python LSP path with:

  ```powershell
  $env:AP_LSP_ENABLED = "true"
  $env:AP_LSP_PYTHON_COMMAND = "pylsp"
  docker compose up -d --build backend
  ```

  To turn the flag back off, set `$env:AP_LSP_ENABLED = "false"` and
  recreate the container.

- For one-off migrations:

  ```powershell
  docker compose run --rm backend alembic -c backend/alembic.ini upgrade head
  ```

## Python And Venv

- Create the venv with the `py` shim when available:

  ```powershell
  py -3.12 -m venv .venv
  ```

  The `py` shim lives in `%LocalAppData%\Programs\Python\Launcher\py.exe`
  on a typical Windows install. If `py` is not on PATH, fall back to
  `python -m venv .venv`. Either form must be followed by:

  ```powershell
  .\.venv\Scripts\Activate.ps1
  pip install -e ".[test]"
  ```

  For the real Python LSP path, add the `codeintel` extra:

  ```powershell
  pip install -e ".[test,codeintel]"
  ```

- Inside the venv, prefer the explicit `.\.venv\Scripts\python.exe` form
  in `Start-Process` arguments so the script does not depend on the
  activation state of the parent shell.

- For pytest, isolate the temp directory inside the repo (the default
  Windows TEMP is usually fine; the override is a safety net):

  ```powershell
  New-Item -ItemType Directory -Force .tmp\pytest | Out-Null
  $env:TEMP = (Resolve-Path .tmp\pytest).Path
  $env:TMP = $env:TEMP
  .\.venv\Scripts\python -m pytest backend\tests
  ```

## npm And Frontend

- `npm` from PowerShell sometimes misroutes to the Windows App
  execution alias. Use `npm.cmd` explicitly:

  ```powershell
  Push-Location frontend
  npm.cmd install
  npm.cmd run build
  Pop-Location
  ```

  Or one-shot:

  ```powershell
  npm.cmd install --prefix frontend
  npm.cmd run build --prefix frontend
  ```

- The frontend build is also exposed as a single
  `scripts/validate-local.ps1` step; it is rare that Codex needs to
  invoke it directly.

## Git And Safe.directory

- After a `git clone` to a path under a different user or with a
  redirected drive root, Git for Windows can complain about ownership:

  ```
  fatal: detected dubious ownership in repository
  ```

  The local fix is to mark the repo as safe:

  ```powershell
  git config --global --add safe.directory "C:/Users/SHRUTI RANJAN MAJI/Desktop/my shit/agent-v2"
  ```

  Codex must surface this only if the user is reporting the dubious
  ownership error. It should not run `git config --global` blindly.

## Environment Variables

- Always use `$env:NAME = "value"` (PowerShell) rather than
  `export NAME=value` (Bash).
- The following variables are recognized by the local workflow:

  | Variable | Purpose | Default |
  | --- | --- | --- |
  | `AP_BASE_URL` | Backend base URL for the CLI and tests | `http://localhost:8000` |
  | `AP_BACKEND_URL` | Backend base URL for the PowerShell smokes | `$AP_BASE_URL` |
  | `AP_TEST_POSTGRES_URL` | Override Postgres URL for migration smoke | compose default |
  | `AP_LSP_ENABLED` | `true` to enable the real Python LSP path | `false` |
  | `AP_LSP_PYTHON_COMMAND` | Executable name for the LSP | `pylsp` |
  | `AP_LSP_STARTUP_TIMEOUT_SECONDS` | LSP startup timeout | `10` |
  | `AP_LSP_REQUEST_TIMEOUT_SECONDS` | Per-request LSP timeout | `10` |
  | `AP_LSP_SHUTDOWN_TIMEOUT_SECONDS` | LSP shutdown timeout | `5` |
  | `AP_LSP_MAX_RESPONSE_CHARS` | Max LSP response payload size | `200000` |
  | `AP_LSP_WORKSPACE_ROOT` | Workspace root reported to the LSP | `/workspace` |

  Codex must never invent a new `AP_*` variable. If a new variable is
  truly required, it should be added to `docker-compose.yml` defaults and
  documented in `docs/ci.md` and the `README.md` LSP section.

## Smoke Execution Order

The recommended order for a full local validation pass is:

1. `.\.venv\Scripts\python -m compileall backend\app`
2. `.\.venv\Scripts\python -m ruff check backend\app backend\tests`
3. `.\.venv\Scripts\python -m pytest backend\tests`
4. `npm.cmd run build --prefix frontend`
5. `docker compose config`
6. `powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1`
7. `powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -WithDocker`
8. `powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -WithSmokes`

`validate-local.ps1` is the source of truth for "is local validation
green". Codex should never re-implement these steps; it should just
invoke the script with the right flag combination.

## Bash Fallback For Bash-Only Smokes

The three Bash-only smokes (`mcp-plugin-smoke`, `real-mcp-smoke`,
`permission-resume-smoke`) detect Git Bash, WSL, or system Bash. If any
of them is installed, the PowerShell wrapper shells out to it. If none
is installed, the wrapper prints a "Bash optional" message and exits `0`.
The `validate-local.ps1 -WithSmokes` runner classifies that exit as
`skipped`, not `failed`, so the overall validation does not regress when
the user is on a clean Windows install without Git Bash.

If Codex needs to actually run one of these smokes (e.g. for evidence in
a parity audit), it should propose installing Git for Windows or enabling
WSL and then invoking the PowerShell wrapper. Codex must not paste the
inner `bash scripts/foo.sh` invocation as the primary suggestion, because
that bypasses the wrapper's exit-code plumbing.

## Codex Do / Do Not

Do:

- Use PowerShell call operator with quoted paths.
- Use `Test-Path -LiteralPath`, `Get-Content -LiteralPath`,
  `Remove-Item -LiteralPath`.
- Use `$env:NAME = "value"` for env vars.
- Use `.venv\Scripts\python.exe` and `npm.cmd` explicitly.
- Use `docker compose ...` (space).
- Use `scripts\validate-local.ps1` for "is local validation green?".

Do not:

- Do not use `bash ./script.sh` as the primary local step.
- Do not use `cmd.exe` for new instructions.
- Do not use `export FOO=bar`, `&&`, `||`, `set -e`, `sed -i`, `mktemp`
  in new PowerShell code blocks.
- Do not commit `.env`, private keys, or real model tokens.
- Do not introduce a new `AP_*` env var without updating
  `docker-compose.yml`, `docs/ci.md`, and the `README.md` LSP section.
- Do not run `git config --global` for `safe.directory` without telling
  the user.
