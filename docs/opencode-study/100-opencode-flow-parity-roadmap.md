# OpenCode-Style Flow Parity Roadmap

Generated: 2026-06-06

Baseline: `76cb5e6 Fix GitHub CI observability smoke Python lookup`

This roadmap compares product and runtime flows against OpenCode-style local coding-agent behavior. It is a parity study only; the project should keep its own product identity, implementation choices, and copy.

## Current Read

Overall parity is approximately 71%. The strongest areas are CI/release validation, queue/worker observability, the now-fully-wired CLI/TUI coding flow, permission resume, real stdio MCP, and real-or-fallback LSP code intelligence. The weakest areas are still full-screen terminal polish, provider routing, safe executable plugin flow, and production auth/config hardening.

The previous highest-value batches, queue/worker observability, artifact/session observability, Windows validation, and GitHub CI, are complete. The selected batch for this pass is the local terminal-first coding loop because the runtime is now validated enough to expose a keyboard-native operator path. The follow-up CLI/TUI Batch 2 closes the audit gaps from the earlier "Polish OpenCode-style interactive TUI flow" commit (`d8261be`) by adding the missing commands, the real modal state machine, and the real retry wiring.

## Selected Batch

Batch: Terminal-first CLI/TUI coding flow (Batch 1 + Batch 2 follow-up).

Why this batch:

- It uses the existing Python backend runtime instead of adding a parallel execution path.
- It is local-first, Windows-safe, and Docker-compatible.
- It gives operators a keyboard-native flow for sessions, agents, prompts, events, permissions, human input, queue status, and artifacts.
- It avoids cloud providers, GitHub bot behavior, and model-dependent smoke success.

Implemented in this worktree:

- `backend.app.cli` package with Typer commands, `httpx` API client, `websockets` session stream client, Rich rendering, diff preview helpers, a Rich TUI loop, and an explicit `tui_modals` state-machine module.
- Commands for `health`, `agents`, `sessions list/create/show`, `chat`, `events`, `permissions`, `questions`, `diff`, `queue status`, `queue retry`, `queue show`, `artifact listing`, and `tui`.
- Terminal handlers for permission approval/denial and human-input answer/cancel flows with single-shot state-locked modal helpers (`PermissionModal`, `HumanInputModal`).
- Interactive agent switcher: `agent` opens a picker over `/agents`, validates the id, and applies the selection to the next prompt only.
- Real retry wiring to `POST /queue/jobs/{id}/retry` for both the CLI (`agentv2 queue retry <id>`) and the TUI (`retry` / `retry <job_id>`); conflicts return a non-zero exit code and a clean TUI error.
- File mutation diff preview rendering for `write.file`, `edit.file`, and `patch.apply` metadata when available, with an honest unavailable fallback and safe truncation for very large diffs.
- `scripts/cli-tui-smoke.ps1` extended to validate the new commands, the no-diff case, the queue retry help, and the tui import/start smoke.
- Headless tests in `backend/tests/test_cli_flow.py` and `backend/tests/test_tui_flow.py` covering the new commands, modal state locking, agent switcher, retry conflicts, diff render, and a TUI run-loop smoke.

## Flow Matrix Summary

| Flow | Status | Parity |
| --- | --- | ---: |
| CLI/TUI coding flow | Strong partial | 74% |
| Web/Desktop session flow | Partial | 72% |
| Agent flow | Partial | 62% |
| Tool flow | Partial | 70% |
| Permission flow | Strong partial | 78% |
| LSP/code intelligence flow | Strong partial | 76% |
| MCP flow | Strong partial | 74% |
| Plugin flow | Partial | 58% |
| Memory/compaction flow | Partial | 66% |
| Queue/worker flow | Strong partial | 82% |
| GitHub workflow | Strong partial | 72% |
| Provider/model flow | Partial | 56% |
| Config/project flow | Partial | 60% |
| Artifact/report flow | Partial | 68% |
| Product polish flow | Partial | 52% |

See `docs/opencode-study/flow-parity-matrix.json` for evidence files, reference evidence, risk, validation, and next task for each flow.

## Top 10 Remaining Gaps

1. Promote the Rich TUI to a full Textual-style modal layout with session/agent side panels and durable cursor replay.
2. Push-driven event cursor replay and richer terminal message-part rendering.
3. Safe artifact download or signed URL path when object storage is configured.
4. HTTP/SSE MCP transport and auth flow.
5. Process-isolated plugin execution boundary.
6. Per-workspace supervised LSP process pool.
7. Provider capability matrix and model-routing policy.
8. Project/workspace settings editor with redacted secret handling.
9. Push-driven runtime updates instead of polling-only queue/worker status.
10. Product polish pass for encoding drift, empty/loading states, terminal keyboard accessibility, and web keyboard accessibility.

## Recommended Next Batch

Next after this batch: full terminal TUI polish and project/workspace settings.

Reason: Batch 1+2 proves a terminal-first path through existing APIs and closes the audit gaps. The next improvement is a richer Textual-style modal terminal layout, cursor-aware replay, session switching, and project/workspace scoping before adding more external integration surface.

Validation target:

- Backend compile and Ruff.
- Full backend tests with Windows-safe temp override (187 passed, 4 skipped after the CLI/TUI Batch 2 follow-up).
- Frontend build.
- Docker compose config.
- CLI smoke validates health, agents, sessions, events, permissions, questions, diff (no-diff case), queue status, queue retry help, tui help, and tui import smoke.
- Manual TUI smoke against a live backend.

