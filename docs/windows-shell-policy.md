# Windows Shell Policy

This repository treats **Windows PowerShell as the primary local shell** for
development, validation, and Codex/agent terminal execution. Bash, WSL, and
Git Bash are kept as **compatibility helpers** for the GitHub Actions Linux
pipelines and for the small subset of smoke scripts that have not yet been
ported to PowerShell.

This is a deliberate, project-wide rule. New shell snippets added to the
repository, the README, `docs/`, or `scripts/` must follow this policy. Old
Bash-only examples are tolerated for Linux/CI readers but must be marked as
"CI/Linux helper" and must not be the only way to do a primary validation
step.

## Primary Shell

- **Local development shell**: Windows PowerShell 5.1+ (`powershell.exe`).
- **Local script source of truth**: `scripts/*.ps1`.
- **Local validation entry point**: `scripts/validate-local.ps1`.
- **Container runtime**: Docker Desktop for Windows (Linux container engine).
- **Bash helpers** (`scripts/*.sh`): allowed only when they are:
  1. required by GitHub Actions on `ubuntu-latest`, or
  2. a Linux/macOS convenience mirror of a working PowerShell script.

## Approved Primary Commands

The following command forms are the approved primary interface. Any new
documentation or tool that wants to instruct the user how to run the project
locally must use these forms.

| Task | Approved PowerShell command |
| --- | --- |
| Clone + configure | `git clone ...` then `Copy-Item .env.example .env` |
| Create venv | `py -3.12 -m venv .venv` (fallback: `python -m venv .venv`) |
| Activate venv | `.\.venv\Scripts\Activate.ps1` |
| Install backend | `pip install -e ".[test]"` (add `,codeintel` for the real LSP path) |
| Install frontend | `npm.cmd install --prefix frontend` |
| Start services | `docker compose up -d --build` |
| Apply migrations | `docker compose run --rm backend alembic -c backend/alembic.ini upgrade head` |
| Run pytest | `.\.venv\Scripts\python -m pytest backend\tests` |
| Run compile | `.\.venv\Scripts\python -m compileall backend\app` |
| Run ruff | `.\.venv\Scripts\python -m ruff check backend\app backend\tests` |
| Frontend build | `npm.cmd run build --prefix frontend` |
| Compose config | `docker compose config` |
| Local validation | `powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1` |
| Local validation with smokes | `powershell -ExecutionPolicy Bypass -File scripts\validate-local.ps1 -WithSmokes` |

PowerShell fragments in docs and READMEs must use:

- `.exe` extensions explicitly (e.g. `python.exe`, `npm.cmd`) when calling
  from `Start-Process`, `Invoke-Item`, or another command-exposing tool.
- `$env:VAR = "value"` for environment variables, never `export VAR=...`.
- `Join-Path` and `Resolve-Path` for paths with spaces (the project path
  itself contains a space: `my shit/agent-v2`).
- `Test-Path -LiteralPath` for filesystem checks.
- `Get-Content -LiteralPath` for reading files; never bare `Get-Content`.
- Quote any path that contains spaces with double quotes inside PowerShell
  call operators (`& "path with space\file.ps1"`).

## Conversion Rules (Bash → PowerShell)

When porting a Bash fragment to the primary Windows shell, use the following
mapping. Codex and any other automation that edits documentation must apply
this mapping, not the inverse.

| Bash | PowerShell |
| --- | --- |
| `export FOO=bar` | `$env:FOO = "bar"` |
| `echo $FOO` | `Write-Host $env:FOO` |
| `cp a b` | `Copy-Item a b` |
| `mv a b` | `Move-Item a b` |
| `rm -rf dir` | `Remove-Item -LiteralPath dir -Recurse -Force` |
| `mkdir -p dir` | `New-Item -ItemType Directory -Force -Path dir` |
| `ls` | `Get-ChildItem` |
| `cat file` | `Get-Content -LiteralPath file` |
| `which foo` | `Get-Command foo` |
| `set -e` | `$ErrorActionPreference = "Stop"` |
| `2>&1 | tee log` | `*>&1 | Tee-Object log` |
| `chmod +x file.sh` | not needed on Windows |
| `&&` | `cmd1; if ($?) { cmd2 }` |
| `||` | `cmd1; if (-not $?) { cmd2 }` |
| `./script.sh` | `bash ./script.sh` (helper) **or** PowerShell replacement |
| `source file` | `. .\file.ps1` |
| `head -n 1` | `Get-Content -LiteralPath file -TotalCount 1` |
| `wc -l` | `(Get-Content -LiteralPath file).Count` |
| `jq -r .x.y` | `ConvertFrom-Json` + property access |
| `sed -i 's/a/b/'` | `(Get-Content file) -replace 'a','b' | Set-Content file` |
| `mktemp` | `[System.IO.Path]::GetTempFileName()` |
| `xargs` | `ForEach-Object` (use the pipeline) |

## Codex Terminal Approval Rules

When Codex (or any AI agent editing this repository) needs to run a command
in the user's terminal, it must obey these rules in addition to the user's
own approval prompts:

1. Default to Windows PowerShell. Use the call operator `&` with quoted
   paths when the project root or script path contains spaces.
2. Never propose `bash script.sh` as the primary way to validate locally.
   PowerShell wrappers exist for every required smoke; the only Bash-only
   smokes are `mcp-plugin-smoke`, `real-mcp-smoke`, and
   `permission-resume-smoke`, and they are explicitly marked "Bash optional"
   (see `scripts/*-smoke.ps1`).
3. Do not propose WSL as a primary dependency. WSL may be suggested only as
   a fallback when a Bash-only script must be exercised locally and the user
   asks for it.
4. Do not propose `cmd.exe` as the primary shell; it lacks the parameter
   binding, quoting, and pipeline semantics Codex needs for safe automation.
5. Never run a command that would commit a real `.env`, a real key, a real
   token, or a private key. The pre-commit security scan in
   `scripts/validate-local.ps1`'s pre-push section (and the repo hygiene
   workflow) will block the commit anyway, but Codex must not propose
   `git add .env` style commands.
6. If a user asks for an Ubuntu-style command, Codex should rewrite it to
   the PowerShell form and explain the mapping in the same response, not
   silently keep the Bash form.
7. For Docker operations, prefer the compose v2 plugin form
   (`docker compose ...`) which works identically on Windows PowerShell,
   Git Bash, and WSL. The legacy `docker-compose` form is tolerated for
   the existing `validate-local.ps1` checks but should not be the primary
   form in new docs.

## Compatibility Helpers (Allowed But Not Primary)

The following are allowed and supported, but they are **not** the primary
interface:

- `scripts/validate-local.sh` for Linux/macOS developers.
- `bash scripts/*.sh` for CI parity, manual smoke replication, and the
  three Bash-only smokes.
- WSL for users who explicitly want a Linux-like shell.
- Git Bash for the small set of operators that map cleanly to Bash.

A Bash-only smoke (`mcp-plugin-smoke.sh`, `real-mcp-smoke.sh`,
`permission-resume-smoke.sh`) is allowed to exist; it must have a
PowerShell wrapper that prints "Bash optional" and skips gracefully when
no Bash shell is installed. The wrapper must exit `0` on the skip path so
that `validate-local.ps1 -WithSmokes` continues to be truthful about which
smokes were run.
