# Next Implementation Priorities

Audit commit: `ddae1ec`
Recommended next batch: `P0 CI + CLI/TUI release hardening`

## 1. Restore Green CI

Why: The latest `main` CI failed in the Backend job, so this is the immediate release blocker.

Scope:

1. Fix `backend/tests/test_cli_flow.py::test_cli_tui_help_lists_check_flag` without weakening the intent of the test.
2. Preserve both Windows and Ubuntu CLI behavior.
3. Re-run CI until Backend, Frontend, Migration Smoke, Safe API Smokes, Docker Compose Config, and Repo Hygiene are green.

Acceptance:

1. `agent-platform tui --help` reliably exposes the TUI check/smoke option in CI.
2. Local Windows validation still passes.
3. GitHub Actions CI passes on the pushed commit.

Expected parity impact: +3 to +5 points, mostly in CLI/TUI and CI/release confidence.

## 2. Add Linux-Friendly CLI/TUI Smoke Coverage

Why: Local PowerShell smoke passed, but Ubuntu CI did not fully agree with local behavior.

Scope:

1. Add or update a Bash-compatible TUI smoke that checks `tui --help` and `tui --check`.
2. Run it in CI after backend setup.
3. Keep it independent of real Ollama generation.

Acceptance:

1. Smoke passes on Ubuntu CI and Windows local validation.
2. The smoke verifies health/session/API preconditions clearly.
3. Failures produce actionable logs.

Expected parity impact: +2 to +3 points.

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
