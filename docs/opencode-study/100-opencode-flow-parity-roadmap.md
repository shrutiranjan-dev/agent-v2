# OpenCode-Style Flow Parity Roadmap

Generated: 2026-06-06

Baseline: `f7b1ad1 Add queue worker observability dashboard`

This roadmap compares product and runtime flows against OpenCode-style local coding-agent behavior. It is a parity study only; the project should keep its own product identity, implementation choices, and copy.

## Current Read

Overall parity is approximately 64%. The strongest areas are queue/worker observability, permission resume, real stdio MCP, and real-or-fallback LSP code intelligence. The weakest areas are CLI/TUI coding flow, GitHub automation, product polish, provider routing, and safe executable plugin flow.

The previous highest-value batch, queue/worker dashboard observability, is already complete in `f7b1ad1`. The next highest-value batch selected for this pass is artifact/session observability because it completes the operator story around queued work: once a run finishes, users need to see what outputs were produced without exposing object-store internals.

## Selected Batch

Batch: Artifact/session observability plus worker stats alias.

Why this batch:

- It builds directly on the queue dashboard shipped in `f7b1ad1`.
- It is local-first and Windows-safe.
- It improves release confidence without requiring new credentials, external services, or unsafe plugin execution.
- It removes a product/security footgun where the dashboard displayed artifact storage object keys.

Implemented in this worktree:

- Safe artifact serialization that omits `bucket` and `object_key`.
- Redacted artifact metadata for obvious sensitive keys.
- `GET /artifacts/{id}`.
- `GET /sessions/{id}/artifacts`.
- `GET /workers/stats`.
- Dashboard session detail artifact visibility.
- Dashboard artifact cards based on safe metadata and download status.
- Focused backend regression tests for artifact detail, session filtering, redaction, and worker stats.

## Flow Matrix Summary

| Flow | Status | Parity |
| --- | --- | ---: |
| CLI/TUI coding flow | Missing | 20% |
| Web/Desktop session flow | Partial | 72% |
| Agent flow | Partial | 62% |
| Tool flow | Partial | 70% |
| Permission flow | Strong partial | 78% |
| LSP/code intelligence flow | Strong partial | 76% |
| MCP flow | Strong partial | 74% |
| Plugin flow | Partial | 58% |
| Memory/compaction flow | Partial | 66% |
| Queue/worker flow | Strong partial | 80% |
| GitHub workflow | Missing | 25% |
| Provider/model flow | Partial | 56% |
| Config/project flow | Partial | 60% |
| Artifact/report flow | Partial | 68% |
| Product polish flow | Partial | 52% |

See `docs/opencode-study/flow-parity-matrix.json` for evidence files, reference evidence, risk, validation, and next task for each flow.

## Top 10 Remaining Gaps

1. CLI/TUI session loop for keyboard-native coding.
2. GitHub Actions CI for backend, frontend, migrations, and smoke scripts.
3. Safe artifact download or signed URL path when object storage is configured.
4. HTTP/SSE MCP transport and auth flow.
5. Process-isolated plugin execution boundary.
6. Per-workspace supervised LSP process pool.
7. Provider capability matrix and model-routing policy.
8. Project/workspace settings editor with redacted secret handling.
9. Push-driven runtime updates instead of polling-only queue/worker status.
10. Product polish pass for encoding drift, empty/loading states, and keyboard accessibility.

## Recommended Next Batch

Next after this batch: GitHub CI and smoke automation.

Reason: The platform now has enough runtime surface area that release confidence depends on repeatable CI, not only local validation. CI should run compile, Ruff, pytest, frontend build, migration smoke, and selected Docker-backed smokes behind explicit environment gates.

Validation target:

- Backend compile and Ruff.
- Full backend tests with Windows-safe temp override.
- Frontend build.
- Alembic upgrade head.
- Docker compose config.
- Queue worker smoke.
- Artifact/session observability smoke once a live backend is running.
