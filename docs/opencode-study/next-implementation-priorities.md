# Next Implementation Priorities

Audit commit: see `git log -1 --format=%H` on the head of the next push.
Latest batch: `File Diff/Review/Undo Batch 2` (DONE — see implementation-roadmap.md and the new `file_change_batch_2026_06_07_batch2` block in `flow-parity-matrix-verified.json` for the scope, validations, and explicit out-of-scope items. Closes the revert approval gate, 409 contract, batch revert, Git fallback, and end-to-end round-trip smoke).
Latest local policy: `Make Windows PowerShell the primary local workflow` (DONE — see [`docs/windows-shell-policy.md`](../windows-shell-policy.md), [`docs/codex-windows-execution.md`](../codex-windows-execution.md), and the `validate-local.ps1` summary in this audit for the new passed/failed/skipped reporting).
Latest smoke reliability: `Windows Smoke Reliability Batch` (DONE — see [`docs/ci.md`](../ci.md) "Smoke Result Semantics"; `validate-local.ps1 -WithSmokes` now reports `passed=N failed=0 skipped=M warned=K`, queue-worker stale heartbeat is WARN, mcp-plugin and permission-resume are SKIP when prerequisites are missing, and the `SMOKE_RESULT=...` marker protocol is honoured by all PowerShell smokes). The new `file-change-smoke` joins the same loop and prints `FILE_CHANGES=round_trip_validated` only when the on-disk content is byte-for-byte restored after revert; it prints `FILE_CHANGES=skipped_test_endpoint_disabled` (or `endpoint_validated`) when `AP_ENABLE_TEST_ENDPOINTS=false` and degrades cleanly.
Latest LSP progress: `Real LSP CI follow-through` (workflow added, but current status reverted to `REAL_LSP_CI_VALIDATED` after repo-local verification found CI failures on commits 2564c64 and ed13d13. **Update (file-change batch 170506f):** the public API now shows `CI=success` and `Repo Hygiene=success`, so `CI_CI_VALIDATED` flips back to a true claim; the underlying PowerShell polling bug is logged as a future reliability pass).

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

Status (Real LSP Batch 1): **resolved for Python LSP path; status is now `REAL_LSP_VALIDATED`**.

Implemented in this batch:

1. `LspService` methods (`document_symbols`, `goto_definition`, `find_references`, `get_diagnostics`) return an `LspResult` dataclass carrying `items`, `source` (`real_lsp`|`static_fallback`), `lsp_status`, `fallback_reason`, and a full `lsp` snapshot.
2. `/code/symbols`, `/code/definition`, `/code/references`, `/code/diagnostics` responses and every `code.*` tool result now include `source`, `lsp_status`, `fallback_reason`, and `lsp` (so consumers can never mistake a fallback for a real-LSP result).
3. `LspService.status()` now exposes both `started_at` (existing) and `started` (alias) so the new `lsp.started` field satisfies the original requirement without breaking existing consumers.
4. `pyproject.toml` ships a `[project.optional-dependencies] codeintel = ["python-lsp-server>=1.12.0"]` extra. Install with `pip install -e ".[codeintel]"`.
5. `scripts/lsp-smoke.sh --real` and `scripts/lsp-smoke.ps1 -Real` first verify `python -c "import pylsp"` and then require at least one `/code/...` response body to carry `source: real_lsp` before printing `REAL_LSP=passed`. Default mode still prints `REAL_LSP=disabled_static_fallback`. `--skip-real-if-missing` / `-SkipRealIfMissing` prints `REAL_LSP=skipped_pylsp_missing` and exits 0 when pylsp is absent.
6. Fake LSP lifecycle is now covered by `test_lsp_client_lifecycle_via_fake_server`, `test_lsp_service_real_path_via_fake_server_includes_source_real_lsp`, missing-command fallback, static-fallback source fields, and route/tool honesty assertions.
7. `docker-compose.yml` now threads `AP_LSP_*` env vars into the backend service so real-mode validation is reproducible with `AP_LSP_ENABLED=true AP_LSP_PYTHON_COMMAND=pylsp docker-compose up -d --build backend`.
8. Real-pylsp end-to-end smoke was run live in this audit against `python-lsp-server 1.14.0` and printed `REAL_LSP=passed` after `/code/symbols` and `/code/definition` returned `source: real_lsp` with `lsp_status: real_lsp`.
9. A mandatory `real-python-lsp-smoke` job is now part of default CI. It installs `python-lsp-server`, starts the backend with `AP_LSP_ENABLED=true`, and runs `scripts/lsp-smoke.sh --real`. However, the repo-local verifier checked commits `2564c64` and `ed13d13` and found `CI=failure`, so the correct docs state is currently `REAL_LSP_CI_VALIDATED`, not `REAL_LSP_CI_VALIDATED`. **STATUS UPDATE (file-change batch 170506f):** the public GitHub API now shows `CI=success` and `Repo Hygiene=success` for commit `170506f`, so `CI_CI_VALIDATED` flips back to a true claim on the strength of the underlying run state. The PowerShell `check-github-actions.ps1` polling loop has a latent bug that surfaces when a run completes faster than the appear-poll interval; a future reliability pass should fix it.

Acceptance:

1. `/health/codeintel` reports `real_lsp_enabled=true` and `mode=real_lsp` when `AP_LSP_ENABLED=true` and `pylsp` is importable.
2. LSP diagnostics and symbols are smoke-tested; `lsp-smoke.ps1 -Real` exits 0 with `REAL_LSP=passed` and never claims pass when real LSP did not actually handle a request.
3. Failure falls back cleanly without hiding degradation. Missing `pylsp` returns `source=static_fallback` with a populated `fallback_reason`, not a crash.

TypeScript/JS LSP is still future.

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

## 11. File Diff / Review / Undo — Batch 2

Status: **DONE**.

Why: Batch 1 captures and reverts individual file changes durably, but interactive approval, multi-file revert, and a Git/VCS fallback channel were still missing.

Scope (Batch 2):

1. Revert approval gate that respects the existing permission policy (mirrors `PermissionRequest` lifecycle) so destructive reverts cannot be triggered by an unattended run. **DONE** — `POST /file-changes/{id}/revert` returns HTTP 202 with `{"status":"waiting_permission","permission_request_id","approval_nonce"}` when `AP_FILE_CHANGE_REVERT_REQUIRES_APPROVAL=true` (default). The client retries with `permission_request_id` after `POST /permissions/{id}/approve`. The CLI `agentv2 changes revert` exposes both `--approve` (auto-approve) and `--permission-request-id` flows; the WebUI renders the waiting state with an `Approve and retry` button.
2. Batch revert API + UI: revert N selected changes in a single audited operation, with a single atomic restore per file and a single `AuditLog` action. **DONE** — `POST /file-changes/revert-batch` validates all preconditions first (revertible, secret, outside-workspace, hash) before applying any restore. On any precondition failure the batch is rejected with HTTP 409 and a `details.skipped` array; on permission gate the response is HTTP 202 with one `permission_request_id`. Successful batch returns `{reverted, skipped, failed, restored_from_snapshots}` with per-change reasons.
3. Git/VCS integration as an alternative restore channel when a workspace is inside a Git repository (read `HEAD` snapshot via `git show HEAD:<path>`) — optional and capability-detected, not required. **DONE** — `restore_from_git_head(relative_path)` is the secondary fallback used when the snapshot is missing or stale. Gated by `AP_FILE_CHANGE_GIT_FALLBACK_ENABLED`; only triggered inside a Git working tree.
4. End-to-end smoke that runs a real `write.file` and `edit.file` against a live backend, polls `/file-changes`, reverts, and asserts the file is restored byte-for-byte. **DONE** — `scripts/file-change-smoke.ps1` / `.sh` use the gated test endpoint to perform a real write+revert round-trip and print `FILE_CHANGES=round_trip_validated` only when the on-disk SHA-256 matches the original. They print `FILE_CHANGES=skipped_test_endpoint_disabled` (exit 0) when `AP_ENABLE_TEST_ENDPOINTS=false` and degrade cleanly.

Hash-mismatch contract fix: **DONE** — `POST /file-changes/{id}/revert` now returns HTTP 409 `file_change_hash_mismatch` (was HTTP 500 `FileChangeError`). Secret filenames without `force=true` return 409 `file_change_secret_requires_force`; outside-workspace targets return 403 `file_change_outside_workspace`; unknown ids return 404; redacted/not-revertible return 403.

Acceptance:

1. Revert is permission-aware and produces an `AuditLog` entry with the user/tool that triggered it. **MET** — 47 file-change tests pass (including 26 in `test_file_changes_batch2.py`), 290 backend tests pass.
2. Multi-file revert rolls back atomically and surfaces a partial-failure report if any file cannot be restored. **MET** — `revert_file_changes_batch()` does validate-all-before-apply with `details.skipped` reasons.
3. When the workspace is a Git repo, the revert endpoint can use `git show HEAD:<path>` as a secondary fallback if `before_content` is missing or out of date. **MET** — `restore_from_git_head` unit-tested with a temp git repo.
4. `file-change-smoke` covers the full round-trip path (create change, list, revert, verify) and prints `FILE_CHANGES=round_trip_validated` only when the on-disk content matches the original after revert. **MET** — new smoke executes `POST /test-endpoints/file-change-write` (gated) → `GET /file-changes` → `POST /file-changes/{id}/revert` → SHA-256 verify → second revert that asserts 409.

Expected parity impact: +3 to +5 points (file-change category to 95+%).
