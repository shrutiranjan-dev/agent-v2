# OpenCode-Style Flow Parity Roadmap

Generated: 2026-06-06

Baseline: `76cb5e6 Fix GitHub CI observability smoke Python lookup`

This roadmap compares product and runtime flows against OpenCode-style local coding-agent behavior. It is a parity study only; the project should keep its own product identity, implementation choices, and copy.

## Current Read

Overall parity is approximately 69%. The strongest areas are CI/release validation, queue/worker observability, permission resume, real stdio MCP, and real-or-fallback LSP code intelligence. The weakest areas are still full-screen terminal polish, provider routing, safe executable plugin flow, and production auth/config hardening.

The previous highest-value batches, queue/worker observability, artifact/session observability, Windows validation, and GitHub CI, are complete. The selected batch for this pass is the local terminal-first coding loop because the runtime is now validated enough to expose a keyboard-native operator path.

## Selected Batch

Batch: Terminal-first CLI/TUI coding flow.

Why this batch:

- It uses the existing Python backend runtime instead of adding a parallel execution path.
- It is local-first, Windows-safe, and Docker-compatible.
- It gives operators a keyboard-native flow for sessions, agents, prompts, events, permissions, human input, queue status, and artifacts.
- It avoids cloud providers, GitHub bot behavior, and model-dependent smoke success.

Implemented in this worktree:

- `backend.app.cli` package with Typer commands, `httpx` API client, `websockets` session stream client, Rich rendering, diff preview helpers, and a lightweight Rich TUI loop.
- Commands for health, agents, session list/create/show, chat, queue status, artifact listing, and TUI.
- Terminal handlers for permission approval/denial and human-input answer/cancel flows.
- File mutation diff preview rendering for `write.file`, `edit.file`, and `patch.apply` metadata when available, with an honest unavailable fallback.
- `scripts/cli-tui-smoke.ps1` for deterministic PowerShell validation.
- Headless tests for client calls, command parsing, renderers, permission prompts, human-input prompts, and diff preview.

## Flow Matrix Summary

| Flow | Status | Parity |
| --- | --- | ---: |
| CLI/TUI coding flow | Partial | 58% |
| Web/Desktop session flow | Partial | 72% |
| Agent flow | Partial | 62% |
| Tool flow | Partial | 70% |
| Permission flow | Strong partial | 78% |
| LSP/code intelligence flow | Strong partial | 76% |
| MCP flow | Strong partial | 74% |
| Plugin flow | Partial | 58% |
| Memory/compaction flow | Partial | 66% |
| Queue/worker flow | Strong partial | 80% |
| GitHub workflow | Strong partial | 72% |
| Provider/model flow | Partial | 56% |
| Config/project flow | Partial | 60% |
| Artifact/report flow | Partial | 68% |
| Product polish flow | Partial | 52% |

See `docs/opencode-study/flow-parity-matrix.json` for evidence files, reference evidence, risk, validation, and next task for each flow.

## Top 10 Remaining Gaps

1. Full-screen modal TUI polish for keyboard-native coding.
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

Reason: Batch 1 proves a terminal-first path through existing APIs. The next improvement is a richer modal terminal layout, cursor-aware replay, session switching, and project/workspace scoping before adding more external integration surface.

Validation target:

- Backend compile and Ruff.
- Full backend tests with Windows-safe temp override.
- Frontend build.
- Docker compose config.
- CLI health/agents/session smoke.
- Manual TUI smoke against a live backend.
