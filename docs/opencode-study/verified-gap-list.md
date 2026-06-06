# Verified OpenCode Parity Gap List

Audit commit: `ddae1ec`
Verified overall parity: 70%
Release status: blocked by failing GitHub CI Backend job

## P0 Release Blockers

1. GitHub CI Backend job fails on `backend/tests/test_cli_flow.py::test_cli_tui_help_lists_check_flag`.
2. The release cannot be called green until CI passes on Ubuntu for Backend, Frontend, Migration Smoke, Safe API Smokes, Docker Compose Config, and Repo Hygiene.
3. Cross-platform CLI/TUI help output is not stable enough; local Windows passes, latest Ubuntu CI fails.

## P1 Product Parity Gaps

1. GitHub bot/workflow parity is largely missing or not proven: webhook handling, signature validation, issue/PR comment command parsing, session lifecycle, plan posting, branch commits, and PR creation.
2. Real LSP parity is not proven because live code intelligence health ran in `static_fallback` with `real_lsp_enabled=false`.
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

1. Bash-based smokes were not run locally because WSL Bash is unavailable on this machine.
2. Human input and memory compaction smokes remain skipped by design when `AP_ENABLE_TEST_ENDPOINTS=false`.
3. Latest local Windows tests differ from Ubuntu CI: local reported `196 passed, 4 skipped`, while CI reported `198 passed, 1 skipped, 1 failed`.
4. Manual end-to-end TUI and browser UX sessions were not recorded as evidence in this audit.

## Strongest Verified Areas

1. Permission and human-in-loop behavior.
2. Native tool execution and safety checks.
3. Core backend/session/queue runtime.
4. Textual CLI/TUI structure and local smoke coverage.
5. Static code intelligence surfaces and tests.

## Weakest Verified Areas

1. GitHub bot/workflow automation.
2. Release confidence while CI is red.
3. Real LSP enabled-mode operation.
4. MCP HTTP/SSE/OAuth/plugin execution parity.
5. Production artifact/report/export flow.
