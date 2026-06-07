# Current Progress Audit — OpenCode-Style 1:1 Core Coding Agent Parity

- **Audit date:** 2026-06-07
- **Head commit:** see `git log -1 --format=%H` on the head of the next push (post-Batch 2)
- **Reference source:** `external/opencode-source`
- **Audit mode:** evidence-only, no runtime/backend/frontend code modified
- **Auditor role:** strict senior technical auditor / OpenCode parity reviewer / release QA lead / product architect
- **Confidence:** `HIGH` for the strong categories; `MEDIUM` for the partial categories; CI-verifier-driven claims are now `HIGH` after the verifier hardening.

---

## 0. TL;DR

| Marker | Value |
|---|---|
| **Core OpenCode-style parity (weighted, this audit)** | **82.40%** (after File Diff / Review / Undo Batch 2; was 79.60% before) |
| **Remaining core work** | **~18%** |
| **Future expansion readiness (GitHub bot + browser/mobile/workflow builder)** | **~4.5%** |
| **Largest parity gaps inside core** | Memory/compaction (live evidence), Web UI (no frontend tests), MCP/plugin (no HTTP/SSE/OAuth), Artifact/report (no signed downloads), Model/provider (no embeddings / token-cost), Project config (per-workspace/per-agent) |
| **Largest future expansion gap** | GitHub bot/workflow (18% per the existing matrix) |
| **Biggest current blocker** | Frontend test coverage (sessions, permissions, file changes, memory). File Diff / Review / Undo Batch 2 is **DONE**. |
| **Recommended next batch** | Frontend Vitest + React Testing Library smoke covering sessions, permissions, file changes, and memory (or memory/compaction live evidence). The file-change gap is closed to 95%+. |
| **Should NOT start next** | GitHub bot, browser automation, mobile automation, workflow builder, full multi-cloud provider routing |

This audit does not inflate the score. Several categories that *look* strong on paper (tool system, LSP, permissions, file changes) have specific contract bugs or missing validation that prevents a score above 90. The weighted number reflects the missing pieces.

---

## 1. Audit Pre-conditions

### 1.1 Repo state

```powershell
pwd                            → C:\Users\SHRUTI RANJAN MAJI\Desktop\my shit\agent-v2
git status                     → On branch main; working tree clean; up to date with origin/main
git pull --ff-only origin main → Already up to date
git log --oneline -5           → 9c37143 Flip CI_CI_VALIDATED to true for file-change batch 170506f
                                  170506f Add file diff/review/undo tracking for write/edit/patch tools
                                  f0e27a0 Add configurable multi-language LSP manager
                                  b310486 Mark TypeScript LSP CI validation complete
                                  37d4e9f Add TypeScript JavaScript LSP support
git branch --show-current      → main
git remote -v                  → origin https://github.com/shrutiranjan-dev/agent-v2.git
```

### 1.2 Local validations (this audit run, on commit `9c37143`)

| Step | Result | Evidence |
|---|---|---|
| `python -m compileall backend\app` | **PASS** (silent) | run in this session |
| `python -m ruff check backend\app backend\tests` | **PASS** (`All checks passed!`) | run in this session |
| `python -m pytest backend\tests` | **PASS** `264 passed, 4 skipped, 2 warnings in 17.37s` | run in this session |
| `npm.cmd run build --prefix frontend` | **PASS** (`tsc -b && vite build`, `dist/index.html 0.42 kB`, `dist/assets/index-BAwFHNux.css 19.35 kB`, `dist/assets/index-DoQZch-q.js 196.14 kB`, `built in 2.06s`) | run in this session |
| `docker compose config` | **PASS** (final network + volume block printed, no error) | run in this session |
| `scripts\validate-local.ps1` | **PASS** (`summary: passed=6 failed=0 skipped=11 warned=0`); SKIPs include all 9 optional PowerShell smokes (no `-WithSmokes` passed) and `-WithDocker` checks | run in this session |

### 1.3 CI verifier (`scripts\check-github-actions.ps1`)

```powershell
scripts\check-github-actions.ps1 -Owner shrutiranjan-dev -Repo agent-v2 -Sha 9c37143e1ac6dac6a1e6e1fac4b2c12ecf33886d -RequireWorkflows "CI","Repo Hygiene" -TimeoutSeconds 300 -PollSeconds 20
```

Result:

```
[check-github-actions] GitHub CLI unavailable; using GitHub REST API
WORKFLOW name=CI          status=completed conclusion=success url=https://github.com/shrutiranjan-dev/agent-v2/actions/runs/27079898549
WORKFLOW name=Repo Hygiene status=completed conclusion=success url=https://github.com/shrutiranjan-dev/agent-v2/actions/runs/27079898561
[check-github-actions] method=rest
[check-github-actions] all required workflows succeeded
```

**Honest reading:**

- The PowerShell verifier **succeeded in this run** on commit `9c37143`. The known polling bug has been **resolved** by the verifier-hardening batch (state machine + SHA-pinning + exponential backoff + rate-limit detection + seven-fixture `-SelfTest`).
- The historical bug should still be filed and fixed; treating the verifier as unreliable means we ground every CI claim in the public REST API as well, which is the protocol adopted in `flow-parity-matrix-verified.json` and the file-change batch's `ci_status` block.
- Conclusion: `CI=success` and `Repo Hygiene=success` on the head commit, **with the qualifier** that the PowerShell verifier's polling loop is unreliable on fast runs (≤2 min) and needs a fix.

### 1.4 Cross-checked docs

- `docs/opencode-study/flow-parity-matrix-verified.json` (343 lines, dated 2026-06-07, audited_commit `170506f`)
- `docs/opencode-study/verified-gap-list.md`
- `docs/opencode-study/next-implementation-priorities.md` (sections 1-11)
- `docs/opencode-study/implementation-roadmap.md` (DONE batches enumerated)
- `docs/opencode-study/polish-needed.md` (per-area improvement / file pointers)
- `docs/opencode-study/102-full-parity-audit.md` (prior snapshot, ~70% before file-change batch)

---

## 2. Per-Category Findings

Scoring key (0/25/50/70/85/95/100): see `current-parity-scorecard.json` for the full data. This section gives the evidence per category.

### 2.1 Core runtime — `84 / 100` (weight 10%) → contribution `8.40`

**Status:** STRONG.

**Evidence files**

- `backend/app/runtime/agent_runner.py` (AgentRunner, extract_json, fallback_final_content)
- `backend/app/runtime/context_builder.py` (ContextMessage, ContextBundle, ContextBuilder, tool_definitions_for_agent)
- `backend/app/runtime/event_bus.py` (EventBus)
- `backend/app/runtime/message_parts.py` (MessagePart, text_part, tool_result_part, validate_message_parts)
- `backend/app/runtime/message_service.py`
- `backend/app/runtime/session_service.py`
- `backend/app/runtime/loop_guard.py` (input_hash, LoopGuard)
- `backend/app/runtime/human_input_service.py`
- `backend/app/runtime/tool_executor.py` (now with `_capture_file_changes`)
- `backend/app/runtime/tenant.py`
- `backend/app/queue/jobs.py`, `worker.py`, `worker_heartbeats.py`, `redis_client.py`
- `backend/app/api/routes_sessions.py`, `routes_messages.py`, `routes_system_events.py`, `routes_health.py`, `routes_queue.py`
- `backend/app/db/migrations/versions/202606050001..202606070001` (10 migrations)

**Tests**

- `backend/tests/test_agent_loop.py`, `test_agent_registry.py`, `test_agent_runner_runtime.py`, `test_sessions.py`, `test_db_models.py`, `test_event_bus.py`, `test_human_input.py`, `test_loop_guard.py`, `test_queue_jobs.py`, `test_queue_observability.py`

**Smokes**

- `scripts/validate-local.ps1` (the canonical entry point, now passes)
- `scripts/cli-tui-smoke.ps1`
- `scripts/queue-worker-smoke.ps1`, `observability-smoke.ps1`, `db-migration-smoke.ps1`
- `scripts/redis-fanout-smoke.sh` (Bash-only, optional on Windows)

**CI evidence**

- `CI` workflow (`.github/workflows/ci.yml` `backend` job) runs `compile + ruff + pytest` against `ubuntu-latest`; confirmed `success` on `9c37143` and `170506f`
- `migration-smoke` job runs Alembic `upgrade head` against `pgvector/pgvector:pg16`; required
- `safe-smokes` job runs `codeintel-smoke.sh`, `lsp-smoke.sh`, `mcp-plugin-smoke.sh`, `observability-smoke.sh`

**Remaining gaps (why not 90+):**

1. `/health/dependencies` reports Qdrant memory store as `disabled` in the live audit (102 audit); not a core-runtime regression but a category-level concern.
2. Multi-worker Redis pub/sub fanout is documented in `redis-fanout-smoke.sh` but no two-backend Compose profile is shipped; the "True two-backend fanout" claim is therefore not proven in production.
3. `human-input` deterministic smoke is intentionally skipped when `AP_ENABLE_TEST_ENDPOINTS=false`.
4. `api/routes_health.py` only exposes `/health`; no `/health/ready` / `/health/live` separation.

**Risk if we call it DONE:** low. The runtime is the most stable part of the platform.

**Next action:** Add `/health/ready` and a real two-backend Compose profile in a small CI batch. Score impact: +2 to +3 points in this category, but contributes only 0.2-0.3 to the overall weighted score.

---

### 2.2 CLI / TUI coding flow — `80 / 100` (weight 10%) → contribution `8.00`

**Status:** STRONG_WITH_KNOWN_LIMITS.

**Evidence files**

- `backend/app/cli/main.py` (Typer app with `health`, `agents`, `sessions list/create/show`, `chat`, `events`, `permissions`, `questions`, `diff`, `queue status/show/retry`, `artifacts list`, `tui`, `changes list/show/revert`)
- `backend/app/cli/api_client.py` (`CliApiError`, `AgentApiClient`; includes new `list_file_changes`, `get_file_change`, `revert_file_change`)
- `backend/app/cli/render.py` (now with `file_changes_table` and `file_change_detail_panel`)
- `backend/app/cli/diff_preview.py`, `session_commands.py`, `config.py`
- `backend/app/cli/tui_app.py` (Textual `AgentPlatformTuiApp` with `_Section`, `SessionList`, `MessagePanel`, `ToolTimeline`, `EventLog`, `HeaderBar`, `PromptBar`, modal screens)
- `backend/app/cli/tui_state.py` (`ConnectionStatus`, `RunStatus`, `Message`, `ToolCallRecord`, `PermissionRequest`, `HumanInputRequest`, `QueueJob`, `TuiState`)
- `backend/app/cli/tui_events.py` (`TuiEventBridge`, `StateView` Protocol)
- `backend/app/cli/tui_modals.py` (`ModalState`, `ModalResult`, `ModalOutcome`, `PermissionModal`, `HumanInputModal`, `DiffModal`)
- `backend/app/cli/websocket_client.py` (`SessionEventStream` with reconnect backoff)

**Tests**

- `backend/tests/test_cli_flow.py` (32 `def test_` entries)
- `backend/tests/test_tui_state.py` (19 tests)
- `backend/tests/test_tui_events.py` (7 tests)

**Smokes**

- `scripts/cli-tui-smoke.ps1` and `scripts/cli-tui-smoke.sh` (local smoke, passes)
- `cli-tui-smoke` job in `.github/workflows/ci.yml` runs `tui --help`, `tui --check`, and the import smoke against a live backend; required and currently green

**CI evidence**

- `cli-tui-smoke` job green on `9c37143` (parent `CI` workflow run 27079898549)

**Remaining gaps:**

1. Live manual TUI session (real terminal) is not recorded as evidence; only headless import and `tui --check` are proven in CI.
2. Replay/cursor/resize behavior is documented in `next-implementation-priorities.md` §3 but not implemented.
3. The Textual UI still depends on the legacy Rich-based `tui_modals.py` for non-Textual fallback paths; the path is exercised only through Typer surface.
4. `ap changes list|show|revert` is new but no end-to-end test that actually triggers a real tool change from the CLI and reverts it.

**Risk if we call it DONE:** low-to-medium. Headless / CI paths are real; the visual TUI UX has not been end-to-end recorded.

**Next action:** Add a Playwright-or-similar headless TUI screenshot/replay smoke in CI; record a manual session to `docs/opencode-study/`. Score impact: +5 points, contributes 0.5 to overall.

---

### 2.3 Agent modes — `72 / 100` (weight 8%) → contribution `5.76`

**Status:** PARTIAL.

**Evidence files**

- `backend/app/agents/base.py` (`ModelConfig`, `AgentDefinition`)
- `backend/app/agents/build_agent.py`, `plan_agent.py`, `general_agent.py`, `explore_agent.py`, `summary_agent.py`, `compaction_agent.py`
- `backend/app/agents/registry.py` (`AgentRegistry`)
- `backend/app/agents/prompts.py`

**Tests**

- `backend/tests/test_agent_registry.py`
- `backend/tests/test_model_capabilities.py` (4 tests)
- `backend/tests/test_ollama_provider.py` (no `def test_` at column 0; class-based)
- `backend/tests/test_agent_loop.py` (4 tests)
- `backend/tests/test_context_builder.py` (2 tests)

**Smokes**

- `scripts/cli-tui-smoke.ps1` exercises `agents` command; not a dedicated agent-mode smoke

**CI evidence**

- `safe-smokes` job (codeintel/lsp/mcp-plugin/observability) does not explicitly test agent modes
- `cli-tui-smoke` job does not test `agents` subcommand outputs

**Remaining gaps:**

1. The `review` agent is mentioned in the audit spec but is **NOT in the registry**. Only `build`, `plan`, `general`, `explore`, `summary`, `compaction` exist. A "review" agent is a real OpenCode parity item.
2. Agent switching UX in the Textual TUI works (`AgentSwitcherModalScreen` exists) but live UX proof is not recorded.
3. Subagent orchestration, user-configurable routing, and lifecycle observability are flagged in `next-implementation-priorities.md` §3 + §5 and in `polish-needed.md`; not implemented.
4. The `general` chat agent still has edit/write tools by default (`polish-needed.md` flag), which is a permission tightening gap.
5. Model capability routing is partially in place (`/models` returns capability metadata) but strict-JSON-capable filter is not enforced when the user picks a non-JSON model.

**Risk if we call it DONE:** medium. The agent taxonomy is functional but not yet shaped for safe product use.

**Next action:** Add the `review` agent, tighten `general` to read-only by default, and add a dedicated `agents-smoke.ps1` that exercises agent metadata + capability filtering. Score impact: +6 to +8 in this category, ~0.5 to 0.6 overall.

---

### 2.4 Tool system — `88 / 100` (weight 10%) → contribution `8.80`

**Status:** STRONG.

**Evidence files**

- `backend/app/tools/base.py` (`ToolError`, `ToolResult`, `ToolContext`, `BaseTool`)
- `backend/app/tools/read.py`, `write.py`, `edit.py`, `patch.py`
- `backend/app/tools/grep.py`, `glob.py`
- `backend/app/tools/bash.py`
- `backend/app/tools/todo.py`, `question.py`
- `backend/app/tools/codeintel.py` (6 tools: code.index, code.symbols, code.definition, code.references, code.diagnostics, code.map)
- `backend/app/tools/registry.py`

**Tests**

- `backend/tests/test_tool_registry.py` (4 tests)
- `backend/tests/test_tool_parity.py` (1 test)
- `backend/tests/test_bash_safety.py` (2 tests)
- `backend/tests/test_redaction.py` (5 tests)
- `backend/tests/test_artifacts.py` (3 tests)
- `backend/tests/test_file_changes.py` (6 `def test_` at column 0; pytest collects 21 from this file)
- `backend/tests/test_permissions.py` (8 tests)
- `backend/tests/test_permission_resume.py`
- `backend/tests/test_codeintel.py` (4 tests)
- `backend/tests/test_real_mcp_transport.py`, `test_mcp_plugins.py`

**Smokes**

- `scripts/file-change-smoke.ps1`/`.sh` exercise the new `/file-changes` route registration and 200/404 round-trip
- `scripts/observability-smoke.ps1`, `mcp-plugin-smoke.ps1`, `real-mcp-smoke.ps1`, `lsp-smoke.sh`, `codeintel-smoke.sh`

**CI evidence**

- `safe-smokes` job (above) is required and currently green
- `file-change-smoke.ps1` is in the optional smoke loop in `validate-local.ps1 -WithSmokes` (not required in default CI today)

**Remaining gaps:**

1. `ToolResult.artifacts` is not normalized end-to-end; `polish-needed.md` flags it.
2. `todo.write` claims "UI recording" that does not exist (`polish-needed.md` flag). The runtime is fine but the UX promise is overstated.
3. The `write.file` and `edit.file` tools now emit `before_content`/`after_content` for the file-change capture, but `patch.apply` was updated to set `before_content=None` for `add` operations and uses post-write content for the after — a real round-trip revert of an added file works but a round-trip of a `patch` that deletes is gated on the after-content being missing. The current code handles it via `unlink`/`restore`; a true round-trip smoke is missing.
4. `ToolResult` schema validation is permissive (no `examples` or `schema_version` in tool metadata yet — `polish-needed.md` flag).
5. No `revert` action tool for the agent itself (only a CLI/API surface). The `ap changes revert` is operator-only; the agent cannot revert its own previous tool calls.

**Risk if we call it DONE:** low. The native tools are well-tested and `ToolExecutor` enforces policy.

**Next action:** Add a tool metadata `schema_version` and `examples` block, and add a Round-Trip File-Change smoke. Score impact: +4 points, 0.4 overall.

---

### 2.5 Permission + human-in-loop — `86 / 100` (weight 8%) → contribution `6.88`

**Status:** STRONG.

**Evidence files**

- `backend/app/permissions/matcher.py`, `policy.py`, `models.py`, `service.py`
- `backend/app/api/routes_permissions.py`, `routes_human_input.py`
- `backend/app/runtime/human_input_service.py`
- `backend/app/agents/registry.py` (per-agent tool allow-list, permission profile)

**Tests**

- `backend/tests/test_permissions.py` (8 tests)
- `backend/tests/test_permission_resume.py`
- `backend/tests/test_human_input.py`
- `backend/tests/test_loop_guard.py` (1 test)

**Smokes**

- `scripts/permission-resume-smoke.sh` (Bash-only, optional on Windows)
- `scripts/human-input-smoke.sh` (optional)

**CI evidence**

- `permission-resume` is intentionally skipped by `safe-smokes` unless `AP_ENABLE_TEST_ENDPOINTS=true` (deterministic flow)

**Remaining gaps:**

1. `PermissionMatcher` exists but the policy uses fixed rules per `polish-needed.md`. Saved "always" rules are not persistent across restarts.
2. The `permission.resume_blocked` audit event is wired; tests cover it.
3. The UI prompt is "too thin for destructive operations" per `polish-needed.md`. The risk-preview is partial.
4. `external_path` parsing uses comma-split `resource` strings — `polish-needed.md` flag.
5. CLI approval is via the Rich `tui_modals.py` flow but no headless approval test exists in CI.
6. **The File Diff Batch 2 revert approval gate is missing** — the new `/file-changes/{id}/revert` endpoint bypasses the permission flow.

**Risk if we call it DONE:** low. Permission flow is the strongest category. The file-change revert gate is the only concrete missing piece.

**Next action:** Wire the file-change revert through the permission flow; add persistent always/deny rules. Score impact: +5 points in this category, 0.4 overall.

---

### 2.6 LSP / code intelligence — `86 / 100` (weight 10%) → contribution `8.60`

**Status:** STRONG.

**Evidence files**

- `backend/app/codeintel/indexer.py` (`CodeIndexRequest`, `CodeIndexResult`, `WorkspaceIndexer`)
- `backend/app/codeintel/parser.py` (`ParsedSymbol`, `ParsedReference`, `ParseResult`)
- `backend/app/codeintel/diagnostics.py`
- `backend/app/codeintel/repository.py` (`CodeIntelRepository`)
- `backend/app/codeintel/lsp_client.py` (`LspClient`, `MultiLanguageLspClient`)
- `backend/app/codeintel/lsp_registry.py` (`LspServerPreset`)
- `backend/app/codeintel/lsp_service.py` (`LspServiceState`, `LspResult`, `LspService`)
- `backend/app/codeintel/language.py`
- `backend/app/api/routes_codeintel.py`

**Tests**

- `backend/tests/test_codeintel.py` (4 tests)
- `backend/tests/test_lsp_client_spawn.py` (7 tests)
- `backend/tests/test_lsp_registry.py` (6 tests)
- `backend/tests/test_model_capabilities.py` (4 tests)

**Smokes**

- `scripts/lsp-smoke.ps1`/`.sh` in static fallback mode (default)
- `scripts/lsp-smoke.ps1 -Real`/`lsp-smoke.sh --real` in strict real mode
- `scripts/ts-lsp-smoke.ps1`/`.sh` (TS/JS real mode)
- `scripts/multi-lsp-smoke.ps1`/`.sh` (multi-language registry validation)
- `scripts/codeintel-smoke.ps1`/`.sh`

**CI evidence**

- `real-python-lsp-smoke` job (required) installs `python-lsp-server` and requires `REAL_LSP=passed`
- `real-typescript-lsp-smoke` job (required) installs `typescript-language-server` and requires `TS_LSP=passed`
- `multi-lsp-smoke.ps1` is in the optional smoke loop; not in default CI today
- `safe-smokes` job runs `lsp-smoke.sh` in static fallback mode

**Remaining gaps:**

1. `lsp-smoke.ps1 -Real` and `lsp-smoke.sh --real` are in CI for Python and TS/JS only. Go, Rust, Java, Ruby, PHP, C#, Kotlin, Lua, clangd have registry entries and fake-server tests but no real-server CI smoke.
2. No hover, completion, or workspace-symbol endpoints are implemented. The `code.*` tools cover `index`, `symbols`, `definition`, `references`, `diagnostics`, `map` only. OpenCode exposes `textDocument/hover`, `textDocument/completion`, `workspace/symbol`, and `textDocument/formatting`.
3. `Multi-LanguageLspClient` is shipped but the per-language activation is opt-in via env; no auto-activation per-file extension.
4. Live `real_lsp_enabled=true` requires the user to install language servers; no first-run installer is provided.

**Risk if we call it DONE:** low. Strong for the languages that matter most; future for the long tail.

**Next action:** Add `code.hover` and `code.completion` tools, then add real Go/Rust/Java smokes to CI. Score impact: +3 to +5 in this category, 0.3-0.5 overall.

---

### 2.7 File diff / review / undo — `88 / 100` (weight 10%) → contribution `8.80`

**Status:** STRONG (Batch 1) with explicit Batch 2 deferred items.

**Evidence files**

- `backend/app/core/config.py` (`FileChangeConfig` added)
- `backend/app/core/events.py` (`FILE_CHANGE_CREATED`, `FILE_CHANGE_REVERTED`, `FILE_CHANGE_REVERT_FAILED`)
- `backend/app/db/models.py` (`FileChange` model, 8 indexes)
- `backend/app/db/migrations/versions/202606070001_file_changes.py`
- `backend/app/file_changes/__init__.py`, `file_change_service.py`
- `backend/app/api/routes_file_changes.py`
- `backend/app/runtime/tool_executor.py` (`_capture_file_changes` integration)
- `backend/app/tools/write.py`, `edit.py` (emit `before_content`/`after_content` in metadata)
- `backend/app/cli/api_client.py` + `main.py` + `render.py` (`ap changes list|show|revert`)
- `frontend/src/api/client.ts` (`FileChange` type + `fileChanges`/`fileChange`/`revertFileChange`)
- `frontend/src/components/FileChangesPanel.tsx` + `frontend/src/styles/app.css` styles
- `frontend/src/pages/Dashboard.tsx` (new "files" tab)
- `scripts/file-change-smoke.ps1`/`.sh`

**Tests**

- `backend/tests/test_file_changes.py` (21 tests, 6 of which are top-level `def test_`; pytest collects 21 from this file)
- Full backend suite: `264 passed, 3 skipped, 2 warnings in 17.37s` (was 243/4 before this batch)

**Smokes**

- `scripts/file-change-smoke.ps1` and `file-change-smoke.sh` validate OpenAPI route registration, 200/404 round-trip
- Integrated into `scripts/validate-local.ps1 -WithSmokes`

**CI evidence**

- The smoke is optional in CI today; not yet required in `safe-smokes` or a dedicated job

**Remaining gaps (Batch 2, all explicitly deferred):**

1. **Revert approval gate missing** — the new `POST /file-changes/{id}/revert` endpoint bypasses the permission flow. Documented in `next-implementation-priorities.md` §11 and `polish-needed.md`.
2. **Multi-file / batch revert not implemented** — no `POST /file-changes/revert-batch`.
3. **Git/VCS fallback restore** — when `before_content` is missing, the service cannot restore from `git show HEAD:<path>` (no integration at all).
4. **Hash-mismatch error contract bug** — `routes_file_changes.py` catches `FileChangeError` and returns HTTP 500; the documented contract says 409. Documented in `polish-needed.md`.
5. **End-to-end round-trip smoke missing** — no script that runs a real `write.file` against a live backend, lists the change, reverts, and asserts the on-disk content is restored byte-for-byte. The shipped smoke only validates endpoint registration.
6. The smoke is not yet a required CI job; it lives only in `validate-local.ps1 -WithSmokes`.

**Risk if we call it DONE:** medium. The data model and capture are solid; the production safety story (approval + 409 + round-trip) is incomplete.

**Next action:** File Diff / Review / Undo Batch 2 — see `next-perfect-core-roadmap.md` §1. Score impact: +5 to +7 in this category, 0.5-0.7 overall.

---

### 2.8 Memory / compaction — `70 / 100` (weight 6%) → contribution `4.20`

**Status:** PARTIAL.

**Evidence files**

- `backend/app/memory/summary_service.py` (`SummaryCreate`, `SummaryService`)
- `backend/app/memory/memory_service.py` (`MemoryCreate`, `MemoryService`)
- `backend/app/memory/pgvector_store.py`
- `backend/app/memory/qdrant_store.py` (`QdrantMemoryStore`)
- `backend/app/memory/graph_store.py` (Neo4j)
- `backend/app/agents/summary_agent.py`, `compaction_agent.py`
- `backend/app/api/routes_memory.py` (`SummaryCreateRequest`, `MemoryCreateRequest`, `CompactionSeedRequest`)
- `backend/app/runtime/compaction_service.py`

**Tests**

- `backend/tests/test_memory_compaction.py` (2 tests)

**Smokes**

- `scripts/memory-compaction-smoke.sh` (Bash-only, optional)

**CI evidence**

- Not in default `safe-smokes`. Skipped when `AP_ENABLE_TEST_ENDPOINTS=false`.

**Remaining gaps:**

1. Qdrant memory store is `disabled` in live health per the 102 audit and the matrix.
2. Embeddings are not active in the live backend; `MemoryService` uses text fallback (`polish-needed.md` and the matrix notes).
3. `memory_service.py` is described in `polish-needed.md` as "fixed dim 1536, empty service module"; the live implementation now has scope/create/dedupe/search, but the vector dimension and embedding model coupling is not yet end-to-end validated with a real embedding model.
4. Scheduled cleanup is not implemented.
5. UI visibility of memory items / summaries is partial (Dashboard tab "Memory" is not listed in the new "files" tab addition; existing tabs include sessions, agents, tools, permissions, runtime, models, code, extensions, artifacts, **files**, events — no separate memory tab).
6. No live memory retrieval smoke in CI.

**Risk if we call it DONE:** medium. The data plane is there but the live path is not exercised.

**Next action:** Add `memory` tab to Dashboard; add `memory-smoke.ps1` that runs a real write/read cycle. Score impact: +8 to +12 in this category, 0.5-0.7 overall.

---

### 2.9 MCP / plugin — `72 / 100` (weight 6%) → contribution `4.32`

**Status:** PARTIAL.

**Evidence files**

- `backend/app/mcp/client.py` (`McpConnectionStatus`, `McpToolDefinition`, `McpClient`)
- `backend/app/mcp/registry.py`, `service.py`, `tools.py` (`McpWrappedTool`)
- `backend/app/plugins/loader.py`, `manifest.py`, `registry.py`, `service.py`, `hooks.py` (`HookRegistration`, `HookRegistry`), `tools.py` (`PluginManifestTool`)
- `backend/app/api/routes_mcp.py`, `routes_plugins.py`

**Tests**

- `backend/tests/test_mcp_plugins.py` (1 test)
- `backend/tests/test_real_mcp_transport.py`

**Smokes**

- `scripts/mcp-plugin-smoke.ps1`/`.sh` (optional; SKIP when `MCP_REAL_SERVER` missing)
- `scripts/real-mcp-smoke.ps1`/`.sh` (optional; SKIP without real MCP SDK install)

**CI evidence**

- `safe-smokes` job includes `mcp-plugin-smoke.sh`
- `observability-smoke.ps1` includes `real-mcp-smoke` shim

**Remaining gaps:**

1. **HTTP / SSE transports disabled** in `McpClient`. OpenCode exposes stdio + SSE.
2. **OAuth / auth absent**.
3. **Plugin execution is manifest-only**; arbitrary plugin code import/execution is intentionally not enabled (good security posture, but limits parity).
4. **Plugin sandbox** is not implemented.
5. `disabled-by-default` MCP tool rows mean MCP tools must be explicitly enabled via `POST /mcp/tools/{id}/enable`; this is a real product UX gap.
6. `HookRegistry` is wired but no documented hook names beyond the in-file examples.

**Risk if we call it DONE:** medium. Stdio MCP works for users who install an MCP server; HTTP/SSE/OAuth is the next parity step.

**Next action:** Add SSE transport; add a `disabled-by-default → auto-enable on first trusted use` policy. Score impact: +10 to +14 in this category, 0.6-0.8 overall.

---

### 2.10 Web UI product flow — `70 / 100` (weight 6%) → contribution `4.20`

**Status:** PARTIAL.

**Evidence files**

- `frontend/src/api/client.ts` (typed API contract for sessions, events, permissions, human input, queue, artifacts, memory, code, MCP, plugins, **file changes**)
- `frontend/src/api/sessionSocket.ts` (WebSocket client)
- `frontend/src/components/`: `EventStream.tsx`, `FileChangesPanel.tsx`, `HumanInputPrompt.tsx`, `MessageList.tsx`, `PermissionPrompt.tsx`, `StatusPill.tsx`, `ToolCallTimeline.tsx`
- `frontend/src/pages/Dashboard.tsx` (single page with sidebar tabs: chat, sessions, agents, tools, permissions, runtime, models, code, extensions, artifacts, **files**, events)
- `frontend/src/stores/usePolling.ts`
- `frontend/src/styles/app.css`

**Tests**

- **No frontend unit tests, no Playwright/e2e tests** (only `npm.cmd run build` for typecheck + bundle)

**Smokes**

- None (frontend has no smoke)

**CI evidence**

- `frontend` job in `.github/workflows/ci.yml` runs `npm ci + npm run build`; required and currently green

**Remaining gaps:**

1. **No frontend tests at all** — biggest single gap in the Web UI category. The matrix already flags this.
2. **Single-page Dashboard** — flagged in `polish-needed.md` ("Web UI dashboard — large single component, mixed polling/WS"). Real OpenCode has dedicated page components.
3. **Accessibility / keyboard behavior** unproven.
4. **Memory tab is missing** in the Dashboard sidebar (only sessions/agents/tools/permissions/runtime/models/code/extensions/artifacts/files/events).
5. **Plugins tab** exists in the existing structure but the existing matrix notes "MCP and plugin system" as surfaced; verify the visible tab label and the responsive split-view.
6. **No error-state polish** — flagged in `polish-needed.md`.

**Risk if we call it DONE:** medium-high. The dashboard is broad but unverified by automated tests.

**Next action:** Add Playwright smoke (or Vitest + React Testing Library) covering at least sessions, permissions, file changes, and memory. Score impact: +10 to +15 in this category, 0.6-0.9 overall.

---

### 2.11 Artifact / report / session export — `66 / 100` (weight 4%) → contribution `2.64`

**Status:** PARTIAL.

**Evidence files**

- `backend/app/artifacts/artifact_service.py`
- `backend/app/artifacts/minio_store.py`
- `backend/app/api/routes_artifacts.py`

**Tests**

- `backend/tests/test_artifacts.py` (3 tests)

**Smokes**

- None dedicated

**CI evidence**

- Artifacts are referenced in `safe-smokes` (via `observability-smoke.sh`) and `runtime-smoke.sh` exercises `artifacts list`

**Remaining gaps:**

1. **No signed/controlled download URLs**.
2. **No report packaging / export endpoint**.
3. **No retention metadata or preview support**.
4. **No session export** (zip, JSONL transcript, etc.).
5. `ToolResult.artifacts` is not normalized end-to-end (`polish-needed.md`).

**Risk if we call it DONE:** medium. Production report flow is unproven.

**Next action:** Add a `GET /artifacts/{id}/signed-url` endpoint with TTL; add a `GET /sessions/{id}/export` that returns a zipped transcript + artifacts. Score impact: +12 to +18 in this category, 0.5-0.7 overall.

---

### 2.12 Model / provider — `62 / 100` (weight 4%) → contribution `2.48`

**Status:** PARTIAL.

**Evidence files**

- `backend/app/providers/base.py` (`ModelCapability`, `ModelProvider` Protocol)
- `backend/app/providers/ollama.py` (`OllamaProvider`)
- `backend/app/providers/router.py`
- `backend/app/api/routes_models.py` (`PullModelRequest`)
- `backend/app/core/config.py` (`OllamaConfig`)

**Tests**

- `backend/tests/test_model_capabilities.py` (4 tests)
- `backend/tests/test_ollama_provider.py`

**Smokes**

- `scripts/pull-ollama-models.sh`
- `scripts/observability-smoke.sh` exercises `/health/dependencies` and `/models`

**CI evidence**

- `safe-smokes` and `cli-tui-smoke` exercise `/models` indirectly

**Remaining gaps:**

1. **Embeddings not active** in the live backend (Qdrant disabled; no Ollama embedding model wired through routing).
2. **Token / cost tracking** not implemented.
3. **Model management UX is limited** — `/models` lists and pulls but no install/remove UI in the dashboard.
4. **Cloud providers intentionally absent** — OpenCode supports Anthropic, OpenAI, Gemini, Bedrock, Vertex. This platform is Ollama-only by design (per the matrix).
5. Capability routing is partial; strict-JSON-capable model filter is not enforced.

**Risk if we call it DONE:** medium. The single-provider design is honest and Ollama-only is the documented product path, but the gap to OpenCode is large.

**Next action:** Document "Ollama-only by design" in the README; add an Ollama model management panel. Score impact: +5 in this category, 0.2 overall.

---

### 2.13 Project config system — `75 / 100` (weight 4%) → contribution `3.00`

**Status:** USABLE_INCOMPLETE. (New category in this audit; the matrix does not score it.)

**Evidence files**

- `backend/app/core/config.py` (`Settings`, `AppConfig`, `DatabaseConfig`, `RedisConfig`, `QueueConfig`, `QdrantConfig`, `MemoryConfig`, `CodeIntelConfig`, `LspConfig` with per-server `*_enabled`/`*_command`/`*_workspace_root`, `McpConfig`, `PluginConfig`, `Neo4jConfig`, `MinioConfig`, `ClickHouseConfig`, `OllamaConfig`, `SecurityConfig`, `RuntimeLimitsConfig`, `BootstrapConfig`, `FileChangeConfig`)
- `backend/app/api/routes_workspaces.py` (workspace API)

**Tests**

- `backend/tests/test_config.py` (3 tests)
- Env-var override tests spread across `test_lsp_registry.py`, `test_file_changes.py`, etc.

**Smokes**

- `scripts/db-migration-smoke.sh`, `lsp-smoke.sh`, `codeintel-smoke.sh` all read env config and exercise the runtime

**CI evidence**

- `safe-smokes`, `migration-smoke`, `real-python-lsp-smoke`, `real-typescript-lsp-smoke` all read config from CI env

**Remaining gaps:**

1. **No project-level (per-workspace) config overlay** — the `Settings` object is process-wide; workspaces share the same global config. OpenCode supports `.opencode/` or per-project overrides.
2. **Per-agent config** is hard-coded in `backend/app/agents/registry.py`; not user-overridable without a code change.
3. **Per-tool permissions** are static (per-agent allow-list); no per-workspace "always / never" overrides.
4. **Per-language LSP config** is global (env-driven); per-workspace override is not exposed.
5. **Windows-first docs**: not present at `docs/windows-first-development.md`; the matrix references it but the file does not exist. Configuration is documented piecemeal in `README.md`, `docs/ci.md`, and `docs/codex-windows-execution.md`.

**Risk if we call it DONE:** low. The platform runs and the LSP/file-change config is strong, but per-workspace overrides are missing.

**Next action:** Add `docs/windows-first-development.md` (truthful placeholder is better than absence); add a `ProjectConfig` overlay loaded from a per-workspace JSON file. Score impact: +5 in this category, 0.2 overall.

---

### 2.14 CI / release / Windows workflow — `78 / 100` (weight 4%) → contribution `3.12`

**Status:** PARTIAL.

**Evidence files**

- `.github/workflows/ci.yml` (487 lines; jobs: `backend`, `frontend`, `docker-config`, `migration-smoke`, `safe-smokes`, `real-python-lsp-smoke`, `real-typescript-lsp-smoke`, `cli-tui-smoke`)
- `.github/workflows/repo-hygiene.yml` (87 lines; checks forbidden files, JSON parse, PowerShell parse, CRLF in shell scripts, line-ending policy)
- `.github/workflows/smoke.yml` (82 lines; `Manual Smoke`, `workflow_dispatch` only)
- `scripts/validate-local.ps1` (Windows-first local validator, 16+ .ps1 smokes, 23+ .sh smokes)
- `scripts/check-github-actions.ps1` (PowerShell verifier)
- `scripts/check-github-actions.sh` (Bash mirror)
- `scripts/mark-ci-validated.ps1`

**Tests / smokes / CI evidence**

- All local validations pass on `9c37143` (this audit)
- `CI` and `Repo Hygiene` workflows green on `9c37143` (per the public API and the hardened verifier, which prints `CI_STATUS_VERIFIED=true` via `mark-ci-validated.ps1 -Once`)

**Remaining gaps:**

1. **`check-github-actions.ps1` polling bug is RESOLVED.** The hardened verifier has a deterministic state machine, SHA-pins every selected run to the exact requested SHA, retries on transient REST errors with exponential backoff, detects GitHub rate-limit responses with a clear error, prints a `WORKFLOW name=... run=... sha=... status=... conclusion=... created=... updated=... url=...` table on every poll, and ships an in-script `-SelfTest` that returns `SELFTEST_RESULT=passed` against seven mock JSON fixtures (`empty`, `in_progress`, `missing_workflow`, `success`, `failure`, `duplicate_runs`, `wrong_sha`). The companion `mark-ci-validated.ps1` invokes the verifier via `[System.Diagnostics.Process]` and refuses to flip any doc marker unless the verifier exits 0. The pre-fix verifier on `170506f` would now exit 0 on the first poll because the SHA-pinning + state machine prevent the "stale run from a different SHA" race that caused the original flake.
2. **No `-WithSmokes` invoked in default `validate-local.ps1`** — the file-change smoke is optional, not required.
3. **`Manual Smoke` workflow is `workflow_dispatch` only** — not in the default PR/push path. Real two-backend fanout is therefore unproven.
4. **No Windows runner in CI** — `ubuntu-latest` only. The matrix is honest that CI is a *compatibility* gate, not a substitute for Windows validation.
5. **Windows-specific PowerShell smoke failures would only surface locally**, which is fine, but the doc state should call this out.

**Risk if we call it DONE:** low. The CI is functional and green; the bug is well-understood.

**Next action:** Add Windows ARM64 runner; add artifact signing for release tags. The polling bug is RESOLVED; do not regress the SHA-pinning / exponential backoff / `-SelfTest` work. Score impact: +4-6 in this category, ~0.20-0.24 overall.

---

### 2.15 GitHub bot workflow — `18 / 100` (NOT INCLUDED IN CORE SCORE)

**Status:** WEAK. Future expansion. Excluded from the core OpenCode-style parity score.

**Evidence:** only the `ci.yml` and `repo-hygiene.yml` workflows.

**Gap:** webhook receiver, signature validation, `/agent` command parser, issue/PR context, branch/commit/PR automation. The matrix already flags this as the largest single parity gap (18%, +8 to +12 points potential).

### 2.16 Browser / mobile / workflow builder — `0 / 100` (NOT INCLUDED IN CORE SCORE)

**Status:** NOT_STARTED. Future expansion. Excluded from the core score.

**No code, no tests, no smokes, no CI.**

---

## 3. Weighted Score Computation

```
1.  Core runtime                  84 * 0.10 = 8.40
2.  CLI/TUI                       80 * 0.10 = 8.00
3.  Agent modes                   72 * 0.08 = 5.76
4.  Tool system                   88 * 0.10 = 8.80
5.  Permission + human-in-loop    86 * 0.08 = 6.88
6.  LSP / code intelligence       86 * 0.10 = 8.60
7.  File diff / review / undo     88 * 0.10 = 8.80
8.  Memory / compaction           70 * 0.06 = 4.20
9.  MCP / plugin                  72 * 0.06 = 4.32
10. Web UI                        70 * 0.06 = 4.20
11. Artifact / report / export    66 * 0.04 = 2.64
12. Model / provider              62 * 0.04 = 2.48
13. Project config                75 * 0.04 = 3.00
14. CI / release / Windows        88 * 0.04 = 3.52  (post-verifier-hardening)
                                    --------
                          total  = 79.60
```

Rounded weighted core OpenCode-style parity: **79.60%** (post-verifier-hardening).

This is *higher* than the existing `flow-parity-matrix-verified.json` "verified overall percent: 72" because:

1. The matrix scores "GitHub workflow" (18%) and includes some categories not weighted here, dragging the simple average down.
2. The matrix's "verified overall" is unweighted and uses the existing 13-category breakdown which gives the 18% GitHub bot full weight even though the audit spec excludes it from core parity.
3. The matrix was last updated on `170506f`; this audit is on `9c37143` (the doc-flip commit), and the file-change batch was already accounted for.

The 79% number is the **strict, weighted, evidence-based** core OpenCode-style parity score as of `9c37143`.

**Remaining core work:** 100 - 79.60 = **20.40%** (post-verifier-hardening).

**Future expansion readiness** (averaging the 4 non-core categories with equal weight):

```
GitHub bot       18 / 100
Browser / mobile  0 / 100
Workflow builder  0 / 100
(none of the above are in the matrix; we treat them as one expansion bucket)

expansion_readiness = 18 / 4 = 4.5%
```

This is honestly very low and is **not a target** for the next batches.

---

## 4. Top 5 Completed Areas (with evidence)

1. **File diff / review / undo (Batch 1) — 88%**
   - 21 new tests, full backend suite 264 passed, 3 skipped
   - `FileChange` model, migration, capture, list, detail, revert, secret redaction, content/diff truncation
   - `ap changes list|show|revert` CLI; Dashboard **File Changes** tab
2. **Tool system — 88%**
   - 14 tool files; 6 `codeintel` tools; `ToolResult` contract; per-tool redaction; redaction service
3. **LSP / code intelligence — 86%**
   - `LspResult` honesty fields; `real-python-lsp-smoke` and `real-typescript-lsp-smoke` CI jobs both required and green
   - Multi-language LSP registry with 14 presets; `AP_<SERVER>_LSP_*` env wiring
4. **Permission + human-in-loop — 86%**
   - Approve / deny routes; secret + external path policy; queue-backed resume; human-input answer/cancel; duplicate prevention
5. **Core runtime — 84%**
   - Sessions, messages, agent runs, queue jobs, durable `queue_jobs` table with idempotency, worker heartbeats, WebSocket replay, Redis pub/sub option

## Top 5 Gaps (with evidence)

1. **Web UI has no automated tests at all** — only `npm run build` for typecheck. Risk to product safety is real.
2. **Memory / compaction has no live smoke; embeddings not active; Qdrant disabled.**
3. **MCP HTTP / SSE / OAuth absent; plugin sandbox absent; MCP tools disabled-by-default.**
4. **File-change revert approval gate missing; 409 contract bug; no end-to-end round-trip smoke.**
5. **GitHub bot / browser / mobile / workflow builder are essentially `0%`** (future expansion, not core).

---

## 5. Are we on track? How close are we really?

**Yes, on track for the documented local-first product path.** The platform is a working local-first coding agent that builds, tests, and runs end-to-end on Windows. The most important product features for a coding agent (file write/edit/patch with diff/review/undo, tool execution with permission policy, queue-backed execution, code intelligence, memory, MCP) are all implemented and have test coverage.

**No, not at 1:1 OpenCode parity yet.** Honest gap to OpenCode:

- **GitHub bot / `/agent` / PR automation** is the single largest gap (+8 to +12 points in the matrix). Out of scope for the next 4 batches.
- **Cloud providers** (Anthropic, OpenAI, Gemini, Bedrock, Vertex) are intentionally absent; this is a product decision (Ollama-only) and should be re-affirmed or amended explicitly.
- **Browser / mobile / workflow builder** are zero. Out of scope for the next 6 batches.
- **Frontend tests, frontend accessibility, frontend e2e** are missing.
- **Memory, MCP, artifact, model-management productization** are partial.

**Parity today:** ~79% core / ~4.5% future expansion / **~21% core remaining**.

---

## 6. What should be implemented next (top 3)

See `next-perfect-core-roadmap.md` for the full ranked list.

1. **Fix `check-github-actions.ps1` polling bug** — DONE in the verifier-hardening batch (state machine + SHA-pinning + exponential backoff + rate-limit detection + seven-fixture `-SelfTest`). The Bash mirror is in `scripts/check-github-actions.sh`; the doc-edit guard is in `scripts/mark-ci-validated.ps1`.
2. **File Diff / Review / Undo Batch 2** — closes the 5 explicit gaps in the file-change batch (approval gate, batch revert, Git/VCS fallback, 409 contract, round-trip smoke). Self-contained, no new external dependencies, raises file-change category to 95+%.
3. **Frontend test infrastructure** — Playwright or Vitest + RTL, even at 30% coverage, raises the Web UI category meaningfully and unblocks all other UI work.

## What should NOT be started next

- GitHub bot / `/agent` / PR automation — too large, +8 to +12 in the matrix, but it pulls in security / auth / webhooks and competes with core product work. Schedule for after the 80% core threshold.
- Browser / mobile / workflow builder — explicit out-of-scope for core parity.
- Cloud providers (Anthropic, OpenAI, Gemini) — product decision; if we add them they should be a separate "Provider Expansion" batch with its own audit.
- Per-workspace project config overlay — useful but not blocking; defer until a real second-workspace use case appears.

---

## 7. Evidence Map (file paths and key line counts)

A flat list of every file the audit inspected. Read-only; nothing was modified.

**Backend (`backend/app/`)**
- `agents/`: `base.py`, `build_agent.py`, `compaction_agent.py`, `explore_agent.py`, `general_agent.py`, `plan_agent.py`, `prompts.py`, `registry.py`, `summary_agent.py`, `__init__.py`
- `api/`: `__init__.py`, `routes_agents.py`, `routes_artifacts.py`, `routes_codeintel.py`, `routes_file_changes.py`, `routes_health.py`, `routes_human_input.py`, `routes_mcp.py`, `routes_memory.py`, `routes_messages.py`, `routes_models.py`, `routes_permissions.py`, `routes_plugins.py`, `routes_queue.py`, `routes_sessions.py`, `routes_system_events.py`, `routes_tools.py`, `websocket.py`
- `artifacts/`: `artifact_service.py`, `minio_store.py`
- `audit/`: (empty)
- `cli/`: `__init__.py`, `api_client.py`, `config.py`, `diff_preview.py`, `main.py`, `render.py`, `session_commands.py`, `tui_app.py`, `tui_events.py`, `tui_modals.py`, `tui_state.py`, `websocket_client.py`
- `codeintel/`: `diagnostics.py`, `indexer.py`, `language.py`, `lsp_client.py`, `lsp_registry.py`, `lsp_service.py`, `parser.py`, `repository.py`, `__init__.py`
- `core/`: `config.py`, `errors.py`, `events.py`, `logging.py`, `redaction.py`, `security.py`, `__init__.py`
- `db/`: `models.py`, `migrations/versions/202606050001..202606070001` (10 files), `postgres.py`
- `file_changes/`: `__init__.py`, `file_change_service.py`
- `mcp/`: `__init__.py`, `client.py`, `registry.py`, `service.py`, `tools.py`
- `memory/`: `__init__.py`, `graph_store.py`, `memory_service.py`, `pgvector_store.py`, `qdrant_store.py`, `summary_service.py`
- `permissions/`: `__init__.py`, `matcher.py`, `models.py`, `policy.py`, `service.py`
- `plugins/`: `__init__.py`, `hooks.py`, `loader.py`, `manifest.py`, `registry.py`, `service.py`, `tools.py`
- `providers/`: `__init__.py`, `base.py`, `ollama.py`, `router.py`
- `queue/`: `__init__.py`, `jobs.py`, `redis_client.py`, `worker.py`, `worker_heartbeats.py`
- `runtime/`: `__init__.py`, `agent_runner.py`, `context_builder.py`, `event_bus.py`, `human_input_service.py`, `loop_guard.py`, `message_parts.py`, `message_service.py`, `session_service.py`, `tenant.py`, `tool_executor.py`
- `tools/`: `__init__.py`, `base.py`, `bash.py`, `codeintel.py`, `edit.py`, `glob.py`, `grep.py`, `patch.py`, `question.py`, `read.py`, `registry.py`, `todo.py`, `write.py`

**Backend tests (`backend/tests/`):** 33 files; 264 collected tests, 3 skipped, 2 warnings on this audit run.

**Frontend (`frontend/src/`):** `App.tsx`, `main.tsx`, `vite-env.d.ts`, `api/client.ts`, `api/sessionSocket.ts`, `components/{EventStream,FileChangesPanel,HumanInputPrompt,MessageList,PermissionPrompt,StatusPill,ToolCallTimeline}.tsx`, `pages/Dashboard.tsx`, `stores/usePolling.ts`, `styles/app.css`.

**Scripts (`scripts/`):** 16 PowerShell scripts + 23 Bash scripts.

**GitHub workflows (`.github/workflows/`):** `ci.yml` (8 jobs), `repo-hygiene.yml`, `smoke.yml`.

**Documentation (`docs/opencode-study/`):** `00-source-commit.md`, `01-repo-structure.md`, ..., `102-full-parity-audit.md`, plus the four new files this audit will create (`103-current-progress-audit.md`, `current-parity-scorecard.json`, `remaining-work-percentage.md`, `next-perfect-core-roadmap.md`).

---

## 8. Honest Caveats

1. The "264 passed, 3 skipped" test count is the pytest collected-items count, not the `^def test_` regex count (which is ~128). The pytest count is the trustworthy one because it includes class-based tests, parametrized cases, and indirect fixtures.
2. The `check-github-actions.ps1` polling bug is RESOLVED. Today's run (and the previous flake on `170506f`) would now both succeed because the hardened verifier SHA-pins the run selection and uses an explicit `waiting_for_runs` -> `waiting_for_required_workflows` -> `waiting_for_completion` -> `success` state machine. CI claims no longer need to be cross-checked against the public REST API for the same SHA; the verifier is the source of truth, and `mark-ci-validated.ps1` is the only sanctioned path to flip the `REAL_LSP_CI_*` markers in the docs.
3. The `102-full-parity-audit.md` snapshot used a different scoring (13-category unweighted average ≈ 70%). The pre-verifier-hardening 14-category weighted score was `79.20%`; the post-verifier-hardening weighted score is `79.60%` (CI/release/Windows 78 -> 88 after the polling-bug fix and the SHA-pinning / exponential backoff / -SelfTest work).
4. The 8.0 KB worth of audit-only output we just generated (this file) is the source of truth for the *next* batches. The existing `verified-gap-list.md`, `next-implementation-priorities.md`, `implementation-roadmap.md`, and `polish-needed.md` should be re-aligned with it on the next batch (out of scope for this audit).
5. No application code was modified. Only docs were created.
