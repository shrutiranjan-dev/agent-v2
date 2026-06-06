# OpenCode Full Parity Audit 102

Audit date: 2026-06-06
Repository path: `C:\Users\SHRUTI RANJAN MAJI\Desktop\my shit\agent-v2`
Audited commit: `ddae1ec Promote CLI TUI to Textual full-screen runtime`
Reference source: `external/opencode-source` present locally
Audit mode: evidence-only, no runtime changes

## Executive Finding

The project is not yet a 1:1 OpenCode replica. It is, however, a substantially implemented local-first agent runtime with a strong Python backend, native tool execution, permission and human-input loops, a Textual CLI/TUI, memory primitives, code-intelligence surfaces, artifact APIs, MCP stdio integration, and a broad dashboard.

Verified overall parity is approximately 70%. The previous 74% overall claim is plausible as a directional product estimate, but it is not proven by the latest release state because GitHub CI is currently red on `main`.

The strongest verified areas are tool execution, permission/human-in-loop behavior, backend runtime primitives, and the new Textual TUI implementation. The weakest areas are GitHub bot/workflow parity, provider/model management, production artifact/report handling, real LSP activation, and release confidence while CI is failing.

## Validation Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Python compile | PASS | `.\.venv\Scripts\python -m compileall backend\app` |
| Ruff | PASS | `.\.venv\Scripts\python -m ruff check backend\app backend\tests` |
| Backend tests, local Windows | PASS | `196 passed, 4 skipped, 1 warning` |
| Frontend build | PASS | `npm.cmd run build --prefix frontend` |
| Docker Compose config | PASS | `docker-compose config` |
| Docker backend/worker boot | PASS | `docker-compose up -d --build backend backend-worker` |
| `/health` | PASS | `{"status":"ok","service":"agent-platform-python"}` |
| `/health/dependencies` | DEGRADED | Qdrant memory store disabled; other checked services reported OK |
| `/health/codeintel` | DEGRADED_OK | Service OK, LSP in `static_fallback`, `real_lsp_enabled=false` |
| `/health/mcp` | DEGRADED_OK | Real stdio MCP available; 3 connected servers, 2 failed servers |
| `/health/plugins` | PASS_LIMITED | Plugins enabled, manifest-only execution |
| CLI TUI smoke | PASS | `scripts\cli-tui-smoke.ps1` passed locally |
| Bash smoke scripts | NOT_RUN | Local WSL Bash unavailable; no installed distributions |
| GitHub Repo Hygiene | PASS | Latest `ddae1ec` run succeeded |
| GitHub CI | FAIL | Backend job failed on `test_cli_tui_help_lists_check_flag` |

Latest CI URL: `https://github.com/shrutiranjan-dev/agent-v2/actions/runs/27064801133`

Latest CI failure: Backend job collected 200 tests and ended with `1 failed, 198 passed, 1 skipped, 1 warning`. The failing test expected `--check` in `agent-platform tui --help`; the Typer/Rich help output in Ubuntu CI did not include it. This means the release flow is not green even though local Windows validation passed.

## Verified Scorecard

| Area | Claimed | Verified | Status | Confidence |
| --- | ---: | ---: | --- | --- |
| Core runtime | NOT_PROVEN | 84 | STRONG | HIGH |
| CLI/TUI coding flow | 86 | 80 | STRONG_WITH_CI_BLOCKER | HIGH |
| Agent system | NOT_PROVEN | 72 | PARTIAL | HIGH |
| Tool system | NOT_PROVEN | 84 | STRONG | HIGH |
| Permission and human-in-loop | NOT_PROVEN | 86 | STRONG | HIGH |
| Memory and compaction | NOT_PROVEN | 70 | PARTIAL | HIGH |
| Code intelligence and LSP | NOT_PROVEN | 76 | PARTIAL | HIGH |
| MCP and plugin system | NOT_PROVEN | 72 | PARTIAL | HIGH |
| Web UI product flow | NOT_PROVEN | 70 | PARTIAL | MEDIUM |
| GitHub bot/workflow flow | NOT_PROVEN | 18 | WEAK | HIGH |
| Provider/model flow | NOT_PROVEN | 62 | PARTIAL | HIGH |
| Artifact/report flow | NOT_PROVEN | 66 | PARTIAL | HIGH |
| CI/release flow | NOT_PROVEN | 68 | PARTIAL_BLOCKED | HIGH |

Verified average: 70%.

## Category Notes

### Core Runtime - 84%

The FastAPI backend, session/message/event model, queue plumbing, worker process, database migrations, and health endpoints are implemented and locally validated. Backend compile, lint, tests, Docker boot, and health checks passed.

Remaining gaps are production-grade tenancy/auth hardening, long-running failure recovery evidence, and release confidence while `main` CI is failing.

### CLI/TUI Coding Flow - 80%

The CLI/TUI is no longer a placeholder. `backend/app/cli/tui_app.py` contains a Textual app with session list, message/event panels, tool and queue panels, prompt input, modals for permissions/human input/agent switching/session creation, and keyboard bindings. `backend/app/cli/tui_events.py` streams backend session events into TUI state, and `backend/app/cli/tui_state.py` has reducer-style state handling. Local `scripts\cli-tui-smoke.ps1` passed.

This is still not 86% release-proven because Ubuntu CI currently fails on the TUI help flag assertion. Live manual operation, replay/cursor behavior, terminal resize behavior, and full cross-platform help rendering need stronger evidence.

### Agent System - 72%

The registry includes build, plan, general, explore, summary, and compaction agents with per-agent tools and JSON-capable model selection. Tests verify the registry, hidden agents, and tool boundaries.

Missing parity includes richer subagent orchestration, user-configurable agent routing, stronger lifecycle observability, and OpenCode-level agent UX polish.

### Tool System - 84%

Native tools cover read, write, edit, patch, grep, glob, bash, todo, question, and code intelligence. The executor applies permission policy and emits preview metadata for sensitive mutations. Tests cover registry, bash safety, parity, code intelligence, MCP plugins, and real MCP transport.

Remaining gaps include more complete preview/diff parity for every mutation path, broader tool ecosystem parity, and more UI affordances around tool history and retry.

### Permission And Human-In-Loop - 86%

Permission routes, policy checks, queue-backed resume, human-input answer/cancel flows, secret-file protections, external path guards, duplicate handling, and tests are strong. The TUI and dashboard have surfaces for these flows.

Gaps are persisted user policy controls, richer always/deny rules, and end-to-end smoke coverage with test endpoints intentionally disabled in default runtime.

### Memory And Compaction - 70%

Summary and compaction services, memory persistence, context builder integration, pgvector/Qdrant store code, and tests are present. Local tests passed.

Live dependency health shows Qdrant degraded because the memory store is disabled, embeddings are not proven active, and the memory compaction smoke was not run locally because Bash was unavailable and test endpoints are disabled by design.

### Code Intelligence And LSP - 76%

Static indexing, parser/language support, diagnostics surfaces, route/tool integration, and tests are implemented. `/health/codeintel` reported OK.

The live runtime was in static fallback mode with `real_lsp_enabled=false`, so real LSP parity is not proven. TypeScript/JS LSP depth, diagnostics robustness, and multi-language parity need more evidence.

### MCP And Plugin System - 72%

Real stdio MCP support is present, the SDK is available, health checks report MCP enabled, tests cover plugin and real MCP transport paths, and plugin manifests are loaded.

HTTP/SSE transports are false, OAuth/auth is absent, plugin execution is manifest-only, and sandboxed plugin runtime parity is not proven.

### Web UI Product Flow - 70%

The frontend build passes and the dashboard covers sessions, events, permissions, human input, queue, artifacts, memory, code intelligence, MCP, and plugins.

No frontend unit/e2e tests were part of this audit. The UI is broad but not yet proven to have OpenCode-level flow polish, accessibility, keyboard behavior, or recovery behavior.

### GitHub Bot/Workflow Flow - 18%

GitHub Actions workflows exist, but OpenCode-style GitHub bot parity is not proven. There is no verified webhook/comment command flow, signature validation, issue/PR session lifecycle, plan posting, commit branch automation, or PR creation flow.

This is one of the largest remaining parity gaps.

### Provider/Model Flow - 62%

The local Ollama-oriented provider path, model health, and model selection logic exist. Local health reported Ollama OK with models available.

Embeddings are not active in the live audit, cloud provider parity is intentionally absent, token/cost accounting is not proven, and there is no full local model management UX.

### Artifact/Report Flow - 66%

Artifact package/service/routes are restored, MinIO health was OK, and tests cover artifact behavior. The UI can list related runtime outputs.

OpenCode-level report/export/download parity is not proven. Signed URLs, durable report packaging, artifact previews, and retention controls remain incomplete.

### CI/Release Flow - 68%

CI, Repo Hygiene, frontend, migration smoke, safe API smokes, and Docker config jobs exist. Local validation was broad and mostly green.

The current `main` CI is red in the Backend job. This must be treated as a release blocker until fixed.

## Top Five Strongest Areas

1. Permission and human-in-loop runtime.
2. Native tool system with safety checks.
3. Core backend/session/queue runtime.
4. Textual CLI/TUI implementation.
5. Code intelligence static fallback and API surfaces.

## Top Five Weakest Areas

1. GitHub bot/workflow parity.
2. Green CI/release confidence on current `main`.
3. Real LSP enabled-mode proof.
4. MCP HTTP/SSE/OAuth/plugin execution parity.
5. Production artifact/report/export flow.

## Release Blockers

1. Fix the failing GitHub CI Backend job on `test_cli_tui_help_lists_check_flag`.
2. Re-run CI and require green Backend, Frontend, Migration Smoke, Safe API Smokes, Docker Compose Config, and Repo Hygiene.
3. Add or update a cross-platform TUI help/check smoke so Linux and Windows behavior are both covered.

## Recommended Next Batch

The next implementation batch should be `P0 CI + CLI/TUI release hardening`: fix Linux help rendering/assertion behavior, add a Linux-friendly TUI smoke, prove `tui --check` and help output in CI, and only then continue with deeper TUI polish.

After CI is green, the next highest-impact parity batch is GitHub bot/workflow support because that is the largest product gap relative to OpenCode-style repository automation.
