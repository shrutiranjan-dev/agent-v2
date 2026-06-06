# Next Implementation Priorities

Audit commit: `8d63be8`
Latest batch: `P0 CI + CLI/TUI release hardening` (DONE — see implementation-roadmap.md and the latest commit for the resolution).

## 1. Restore Green CI

Status: **RESOLVED** by the `P0 CI + CLI/TUI release hardening` batch.

Resolution summary:

- `backend/tests/test_cli_flow.py::test_cli_tui_help_lists_check_flag` was made platform-agnostic by checking both `result.stdout` and `result.output` (Click/Typer uses different output channels on different versions).
- New `cli-tui-smoke` job in `.github/workflows/ci.yml` runs `tui --help`, `tui --check`, and an import smoke against a real backend on `pgvector/pgvector:pg16`.
- New PowerShell-native smokes (`codeintel-smoke.ps1`, `lsp-smoke.ps1`, `db-migration-smoke.ps1`) and Bash-delegating wrappers (`mcp-plugin-smoke.ps1`, `real-mcp-smoke.ps1`, `permission-resume-smoke.ps1`) reduce dependence on the local Bash environment.
- New `validate-local.ps1` (and `validate-local.sh` mirror) gives a one-command local validation entrypoint.
- CI now uploads failure artifacts (pytest log, backend log, migration log) to the Actions run page with 7-day retention.
- Repo hygiene now also validates `pyproject.toml` parses, PowerShell scripts parse, both flow parity JSON variants parse, and CRLF in shell scripts is rejected.

Acceptance status:

1. `tui --help` reliably exposes the `--check` flag in CI.
2. Local Windows validation still passes.
3. CI failure artifacts surface actionable logs.

## 2. Add Linux-Friendly CLI/TUI Smoke Coverage

Status: **RESOLVED** by the `P0 CI + CLI/TUI release hardening` batch.

Resolution summary:

- Dedicated `cli-tui-smoke` job in CI runs `python -m backend.app.cli.main tui --help` and `python -m backend.app.cli.main tui --check` against a real backend.
- `cli-tui-smoke.ps1` was extended to also validate the new `--check` flag and import smoke (no terminal required).
- Smoke is independent of Ollama model generation.

Acceptance status:

1. Smoke runs on Ubuntu CI and Windows local validation.
2. Pre-flight health check before the TUI smoke ensures the backend is responsive.
3. Failures surface via uploaded backend log artifact.

## 3. Prove Live TUI Event Flow

Why: The Textual app and event bridge exist, but a live terminal session replay/cursor path is not fully proven.

Scope:

1. Add a headless or scripted TUI event replay test.
2. Verify session events, tool calls, permission prompts, queue updates, and human input states.
3. Record disconnect/reconnect behavior.

Acceptance:

1. Test proves the event bridge updates TUI state from backend events.
2. Duplicate events are ignored.
3. Reconnect behavior is deterministic.

Expected parity impact: +3 to +4 points.

## 4. Implement GitHub Bot Workflow MVP

Why: This is the largest OpenCode-style product gap.

Scope:

1. Add webhook receiver with signature validation.
2. Parse issue/PR comment commands.
3. Create or resume agent sessions from GitHub context.
4. Post plans/results back to GitHub.

Acceptance:

1. A signed test webhook creates a session.
2. A PR comment command triggers a plan/run lifecycle.
3. Results are posted back with safe redaction.

Expected parity impact: +8 to +12 points.

## 5. Enable And Prove Real LSP Mode

Why: Code intelligence is useful now, but live health used static fallback.

Scope:

1. Make real LSP startup reliable in local and CI smoke contexts.
2. Add diagnostics/document-symbol smoke coverage.
3. Keep static fallback as an explicit degraded mode.

Acceptance:

1. `/health/codeintel` can report `real_lsp_enabled=true` in a validated environment.
2. LSP diagnostics and symbols are smoke-tested.
3. Failure falls back cleanly without hiding degradation.

Expected parity impact: +3 to +5 points.

## 6. Expand MCP Beyond Stdio

Why: Real stdio MCP is present, but OpenCode-level integration needs broader transport and auth coverage.

Scope:

1. Add HTTP/SSE transport support where appropriate.
2. Add auth/OAuth design and tests.
3. Define plugin execution boundaries.

Acceptance:

1. Health reports transport status separately.
2. Tests cover success and failure paths.
3. Plugin execution remains sandbox-aware.

Expected parity impact: +4 to +6 points.

## 7. Turn Artifacts Into Reports

Why: Artifacts exist, but production report/export flow is not proven.

Scope:

1. Add signed or controlled download URLs.
2. Add report packaging/export endpoints.
3. Add retention metadata and preview support.

Acceptance:

1. A run can produce a downloadable report bundle.
2. Access is permission-aware.
3. Tests cover retention and missing-object behavior.

Expected parity impact: +3 to +5 points.

## 8. Activate Memory Retrieval Evidence

Why: Memory tests pass, but live dependency health showed memory storage disabled.

Scope:

1. Enable a deterministic local memory retrieval smoke.
2. Prove pgvector/Qdrant behavior in a controlled mode.
3. Keep default CI independent of heavyweight model generation.

Acceptance:

1. Memory write/read/retrieve smoke passes.
2. Disabled-store health is reported truthfully.
3. Embedding behavior is either active and tested or explicitly skipped.

Expected parity impact: +3 to +4 points.

## 9. Add Web UI E2E Coverage

Why: The dashboard is broad, but product behavior is not yet strongly proven.

Scope:

1. Add Playwright or equivalent tests for sessions, events, permissions, human input, queue, artifacts, and code intelligence panels.
2. Verify keyboard and accessibility basics.
3. Capture failure screenshots.

Acceptance:

1. Frontend build and e2e checks pass in CI or a documented smoke workflow.
2. Core dashboard paths are covered.
3. CI logs make UI failures diagnosable.

Expected parity impact: +3 to +5 points.

## 10. Harden Provider/Model Management

Why: Ollama works locally, but model lifecycle and capability UX are still limited.

Scope:

1. Add model capability inspection and user-visible status.
2. Add token/accounting metadata where feasible.
3. Add explicit embedding availability reporting.

Acceptance:

1. Provider health distinguishes chat, JSON, tool, and embedding capabilities.
2. Missing model states are actionable.
3. No default CI path requires Ollama generation.

Expected parity impact: +2 to +4 points.
