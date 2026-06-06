# Verified OpenCode Parity Gap List

Audit commit: `8d63be8`
Verified overall parity: 72% (Code Intelligence and LSP raised to 86% with both fake-LSP path validation AND live real-pylsp 1.14.0 validation in this audit; status is now `REAL_LSP_VALIDATED` for the Python LSP path)
Latest batch: `P0 CI + CLI/TUI release hardening` (DONE; see implementation-roadmap.md and the latest commit for the resolution).
Latest local policy: `Make Windows PowerShell the primary local workflow` (DONE; see [`docs/windows-shell-policy.md`](../windows-shell-policy.md) and [`docs/codex-windows-execution.md`](../codex-windows-execution.md) for the project-wide rule, and the `validate-local.ps1` summary in this audit for the new passed/failed/skipped reporting).
Latest smoke reliability: `Windows Smoke Reliability Batch` (DONE; see `validate-local.ps1 -WithSmokes` now reports `passed=N failed=0 skipped=M warned=K` with no misleading optional failures; queue-worker stale heartbeat is WARN when Docker backend-worker is healthy, mcp-plugin is SKIP when `MCP_REAL_SERVER` is missing, permission-resume is SKIP without `AP_ENABLE_TEST_ENDPOINTS=true`, and the `SMOKE_RESULT=...` marker protocol is documented in [`docs/ci.md`](../ci.md) under "Smoke Result Semantics"). `-RequireOptionalSmokes` now correctly promotes optional `SKIP` and `FAIL` to a required `FAIL` (exits non-zero only with the flag, default remains non-fatal) and the "promoted to required" annotation is scoped per smoke (does not leak across iterations).

## Validation Lanes

- **Local source of truth: Windows PowerShell.** The primary local shell
  is Windows PowerShell 5.1+. `scripts/validate-local.ps1` is the canonical
  "is local validation green?" command on a developer workstation, with
  `-WithDocker` for compose service checks and `-WithSmokes` for the full
  PowerShell smoke surface. The new passed/failed/skipped summary prints
  at the end of every run; the script only exits non-zero on a real
  required failure, never on a `skip`.
- **CI compatibility gate: GitHub Actions on `ubuntu-latest`.** The Linux
  pipeline proves the project still builds, tests, lints, migrates, and
  runs the real `pylsp` smoke on a clean Ubuntu runner. It is a
  compatibility check, not a substitute for local Windows validation.
- **Bash-only smokes are explicitly "Bash optional" on Windows.** The
  PowerShell wrappers for `mcp-plugin-smoke`, `real-mcp-smoke`, and
  `permission-resume-smoke` print a "Bash optional" notice and exit `0`
  on the skip path. `validate-local.ps1 -WithSmokes` classifies those as
  `skipped` (not `failed`) so the overall pass count stays truthful on a
  clean Windows install without Git Bash.
- **`REAL_LSP_CI_VALIDATED` is a stricter claim than
  `REAL_LSP_VALIDATED`.** Local Windows validation is sufficient for
  `REAL_LSP_VALIDATED`. The CI-validated label additionally requires the
  `check-github-actions.ps1` verifier to confirm a green `CI` workflow on
  the public GitHub Actions API; that gate is still pending in this
  audit and must not be flipped without proof.

## P0 Release Blockers

1. ~~GitHub CI Backend job fails on `backend/tests/test_cli_flow.py::test_cli_tui_help_lists_check_flag`.~~ **RESOLVED** by the P0 batch. The test now checks both `result.stdout` and `result.output` to absorb Click/Typer version differences across runners. A dedicated `cli-tui-smoke` CI job exercises `tui --help`, `tui --check`, and import smoke against a real backend.
2. ~~The release cannot be called green until CI passes on Ubuntu for Backend, Frontend, Migration Smoke, Safe API Smokes, Docker Compose Config, and Repo Hygiene.~~ **PARTIALLY RESOLVED.** A new `validate-local.ps1` and dedicated `cli-tui-smoke` CI job significantly improve release confidence. Live CI confirmation is still pending the next push.
3. ~~Cross-platform CLI/TUI help output is not stable enough; local Windows passes, latest Ubuntu CI fails.~~ **RESOLVED** by the test fix above.

## P1 Product Parity Gaps

1. GitHub bot/workflow parity is largely missing or not proven: webhook handling, signature validation, issue/PR comment command parsing, session lifecycle, plan posting, branch commits, and PR creation.
2. Real LSP parity: the LSP-backed service path, response honesty fields, and fake-LSP lifecycle are now implemented and tested. Live real-pylsp 1.14.0 end-to-end smoke was run in this audit against the Docker backend with `AP_LSP_ENABLED=true AP_LSP_PYTHON_COMMAND=pylsp`, printing `REAL_LSP=passed` after `/code/symbols` and `/code/definition` returned `source: real_lsp` with `lsp_status: real_lsp`. Status is now `REAL_LSP_VALIDATED` for the Python LSP path. TypeScript/JS LSP is still future.
3. Real LSP CI follow-through is back to `REAL_LSP_CI_VALIDATED`. The mandatory `real-python-lsp-smoke` job exists in default CI, but the repo-local verifier checked commits `2564c64` and `ed13d13` through the public GitHub REST API and found `Repo Hygiene=success` while `CI=failure`, so `REAL_LSP_CI_VALIDATED` is not currently supportable.
3. MCP parity is partial: stdio is implemented, but HTTP/SSE transports, OAuth/auth, and sandboxed plugin execution are absent or not proven.
4. Provider/model parity is partial: Ollama works locally, but embeddings, token/cost accounting, model management UX, and multi-provider routing are not proven.
5. Artifact/report parity is partial: artifact routes and storage exist, but signed downloads, report packaging, export flows, previews, and retention controls are not proven.

## P2 Runtime And UX Gaps

1. CLI/TUI has a real Textual implementation, but live manual operation, replay/cursor behavior, terminal resize behavior, and full event recovery are not fully proven.
2. Web dashboard build passes, but frontend unit/e2e coverage, accessibility, keyboard behavior, and OpenCode-level interaction polish are not proven.
3. Memory and compaction work in tests, but live dependency health shows Qdrant memory store disabled and embeddings inactive.
4. Agent registry is functional, but richer subagent orchestration, user-configurable routing, and lifecycle observability are incomplete.
5. Tool execution is strong, but complete preview/diff parity and richer tool history/retry UX are still incomplete.

## P3 Evidence Gaps

1. Bash-based smokes were not run locally because WSL Bash is unavailable on this machine. **IMPROVED** â€” PowerShell-native smokes (`codeintel-smoke.ps1`, `lsp-smoke.ps1`, `db-migration-smoke.ps1`) now run without Bash, and the Bash-delegating wrappers (`mcp-plugin-smoke.ps1`, `real-mcp-smoke.ps1`, `permission-resume-smoke.ps1`) automatically pick Git Bash/WSL/system Bash when available.
2. Human input and memory compaction smokes remain skipped by design when `AP_ENABLE_TEST_ENDPOINTS=false`.
3. Latest local Windows tests differ from Ubuntu CI: local reported `196 passed, 4 skipped`, while CI reported `198 passed, 1 skipped, 1 failed`. The Ubuntu failure is now fixed.
4. Manual end-to-end TUI and browser UX sessions were not recorded as evidence in this audit.

## CI/Release Confidence After the P0 Batch

1. New dedicated `cli-tui-smoke` CI job runs `tui --help`, `tui --check`, and the import smoke against a live backend on the runner. Failure artifacts (backend log) are uploaded to the Actions run.
2. New `validate-local.ps1` (and `validate-local.sh` mirror) provides a single one-command local validation entrypoint with `-WithDocker` and `-WithSmokes` flags.
3. New PowerShell-native smokes for codeintel, lsp, db-migration, observability, and queue-worker; Bash-delegating wrappers for mcp-plugin, real-mcp, and permission-resume.
4. CI now uploads failure artifacts for backend pytest (`backend-pytest-log`), migration smoke (`migration-smoke-log`), safe API smokes (`safe-smokes-backend-log`), CLI/TUI smoke (`cli-tui-smoke-backend-log`), and repo hygiene (`repo-hygiene-log`).
5. Repo hygiene now also validates `pyproject.toml` parses, PowerShell scripts parse, both flow parity JSON variants parse, and CRLF in shell scripts is rejected.

The P0 batch alone raises CI/release confidence from PARTIAL_BLOCKED to PARTIAL_WITH_SMOKE_ARTEFACTS. Live CI confirmation (green badge on the latest commit) is the next gate before flipping to STRONG.

## Strongest Verified Areas

1. Permission and human-in-loop behavior.
2. Native tool execution and safety checks.
3. Core backend/session/queue runtime.
4. Textual CLI/TUI structure and local smoke coverage.
5. Static code intelligence surfaces and tests.
6. **NEW** Local CI/release validation ergonomics: one-command `validate-local.ps1`, dedicated CLI/TUI CI job, failure artifacts on every CI job, repo hygiene now covers PowerShell parse, JSON parse, and line-ending policy.

## Weakest Verified Areas

1. GitHub bot/workflow automation.
2. CI green status (improved tooling; live green confirmation still pending the next push).
3. Real LSP enabled-mode operation is validated locally for the Python `pylsp` path, but the machine-verifiable GitHub Actions requirement is not currently satisfied for the commits checked above. TypeScript/JS LSP is still future.
4. MCP HTTP/SSE/OAuth/plugin execution parity.
5. Production artifact/report/export flow.
