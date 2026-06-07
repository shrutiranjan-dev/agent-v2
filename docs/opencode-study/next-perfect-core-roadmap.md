# Next Perfect-Core Roadmap (ranked, weighted-ROI)

**Audit date:** 2026-06-07
**Head commit:** `e7ff465bf22bfa7cccc43ce9841bbdd8371c4d44` (current HEAD; this audit is pre-File-Diff-Batch-2)
**Current weighted core OpenCode-style parity:** **79.60%** (post-verifier-hardening; was 79.20% before)
**Target shape:** the local-first product surface, **not** the GitHub bot / browser / mobile / workflow builder expansion.

**Note:** The previously listed batch #1 (fix `check-github-actions.ps1` polling bug) is **DONE** in the verifier-hardening batch. The hardened verifier lives in `scripts/check-github-actions.ps1`, the Bash mirror in `scripts/check-github-actions.sh`, the doc-edit guard in `scripts/mark-ci-validated.ps1`, and the seven mock JSON fixtures in `scripts/testdata/ci-verifier/`. CI/release/Windows went 78 -> 88 (+0.40 weighted). The remaining batches in this roadmap are renumbered accordingly.

Ranking rule: **(weighted-point gain) / (engineer-day)**, then by **risk** (lower first), then by **audit-cleanliness** (does the work make the next audit easier?).

Each batch lists:
- Why
- Files affected
- Acceptance criteria
- Validation commands
- Expected parity delta (weighted points)
- Risk
- Notes

---

## #1 — Fix `check-github-actions.ps1` polling bug (CI/release/Windows: 78 → 88) — **DONE**

**Why:** This was the audit's #1 caveat and the only known correctness bug in our own tooling. Until the polling race was fixed, every future CI claim had to be cross-checked manually against the public REST API. The fix unblocks trustworthy CI evidence for the rest of the roadmap.

**What landed:**
- `scripts/check-github-actions.ps1` — deterministic state machine (`waiting_for_runs` -> `waiting_for_required_workflows` -> `waiting_for_completion` -> `success` / `failure` / `timeout`); SHA-pinning at selection time (defense in depth); exponential backoff on transient REST errors (1s, 2s, 4s, ... capped at `-MaxPollSeconds`); rate-limit detection with a clear error message; per-poll `WORKFLOW name=... run=... sha=... status=... conclusion=... created=... updated=... url=...` diagnostic table; `-Once` and `-SelfTest` flags; full new flag surface (`-Owner`, `-Repo`, `-Sha`, `-TimeoutSeconds`, `-PollSeconds`, `-MaxPollSeconds`, `-RequireWorkflows`, `-Once`, `-SelfTest`, `-SelfTestDir`).
- `scripts/check-github-actions.sh` — thin correct Bash mirror with the same SHA-pinning and same per-iteration table; structurally validated by `repo-hygiene.yml`'s `bash -n` step.
- `scripts/mark-ci-validated.ps1` — Process-based guard that invokes the verifier via `[System.Diagnostics.Process]`, captures the exit code, and refuses to flip any doc marker unless the verifier exited 0; prints `CI_STATUS_VERIFIED=true` only on success.
- `scripts/testdata/ci-verifier/{empty,in_progress,missing_workflow,success,failure,duplicate_runs,wrong_sha}.json` — seven mock JSON fixtures that the in-script `-SelfTest` parses without contacting the network. The self-test prints `SELFTEST_RESULT=passed` and exits 0.

**Acceptance criteria — all met on the current HEAD (`e7ff465`):**
- `pwsh scripts/check-github-actions.ps1 -SelfTest` -> `SELFTEST_RESULT=passed`, exit 0.
- `pwsh scripts/check-github-actions.ps1 -Sha e7ff465bf22bfa7cccc43ce9841bbdd8371c4d44 -Once` -> CI run 27081316351 and Repo Hygiene run 27081316366 both `completed/success`, exit 0.
- `pwsh scripts/mark-ci-validated.ps1 -Once` -> `CI_STATUS_VERIFIED=true`, exit 0.
- `bash -n scripts/check-github-actions.sh` -> no syntax errors.

**Validation commands:**
```
pwsh scripts/check-github-actions.ps1 -SelfTest
pwsh scripts/check-github-actions.ps1 -Sha (git rev-parse HEAD) -Once
pwsh scripts/mark-ci-validated.ps1 -Once
bash -n scripts/check-github-actions.sh
```

**Expected parity delta:** **+0.40 weighted points** (CI 78→88, weight 4). **Achieved.**
**Risk:** very low. **Time:** 0.5 day. **Notes:** Future audits do not need to cross-check CI claims against the public REST API; the verifier is the source of truth.

---

## #1 (active) — File Diff Batch 2 (File diff/review/undo: 88 → 94)

**Why:** Highest ROI backend batch. The File Diff surface is the only category with **multiple known correctness bugs** (revert returns 500 instead of 409, no approval gate, no batch revert, no git/VCS fallback, no end-to-end round-trip smoke). Fixing these is also a precondition for safely exposing file changes in the Web UI.

**Files affected:**
- `backend/app/file_changes/service.py` — change `revert()` to return a structured `FileChangeConflict` (HTTP 409) when `force=False` and the on-disk hash does not match the recorded hash. Add `revert_batch(turn_id)` and `apply_batch(turn_id, approved_by=...)`.
- `backend/app/api/file_changes.py` — wire the new 409 response; add `POST /api/file-changes/turns/{id}/apply` (approval gate) and `POST /api/file-changes/turns/{id}/revert`.
- `backend/app/file_changes/git_fallback.py` (new) — best-effort three-way merge via `git apply --3way` if the local file has been edited outside the tool.
- `backend/tests/test_file_changes_409.py` (new) — 409 contract test.
- `backend/tests/test_file_changes_batch.py` (new) — batch apply + batch revert test.
- `scripts/file-change-roundtrip-smoke.ps1` (new) — full end-to-end: start session → write file via tool → restart backend → verify on-disk hash matches recorded hash → revert → verify hash returns to original.
- `docs/opencode-study/flow-parity-matrix-verified.json` — update the file_change_batch block to reference this batch.

**Acceptance criteria:**
- `revert` returns HTTP 409 (not 500) for hash mismatch.
- Approval gate blocks apply until a `POST /api/file-changes/turns/{id}/apply?approved_by=<user>` is received.
- Batch revert atomically reverts every change in a turn or rolls back with HTTP 409 listing which files conflicted.
- Round-trip smoke passes locally and in CI.
- All 264 existing tests still pass; +8 new tests.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_file_changes*.py -v
.venv\Scripts\python.exe -m pytest backend/tests -q
pwsh scripts/file-change-roundtrip-smoke.ps1
pwsh scripts/validate-local.ps1 -WithSmokes
```

**Expected parity delta:** **+0.60 weighted points** (File diff 88→94, weight 10).
**Risk:** medium (API contract change; needs Web UI consumer update if Dashboard auto-applies).
**Time:** 2 days.
**Notes:** This is the gating batch for the Web UI test infrastructure (#6); do not start #6 in parallel.

---

## #2 — Agent modes polish (Agent modes: 72 → 84)

**Why:** The plan→build transition is invisible to the user, agent memory dies between modes, and agent telemetry is partial. These are the three top complaints an OpenCode user would file on day one.

**Files affected:**
- `backend/app/agents/plan_mode.py` + `build_mode.py` — add a `requires_approval` flag and a `plan_approval` API.
- `backend/app/api/agents.py` — add `POST /api/agents/{id}/plan/approve` and `POST /api/agents/{id}/plan/reject`.
- `backend/app/memory/store.py` — wire plan→build handoff to write a one-line "plan summary" into long-term memory.
- `backend/app/api/agents.py` — add `GET /api/agents/{id}/stats` (tool-call counts, token usage, last-10 tool names).
- `backend/tests/test_agents_approval.py` (new) — plan→build approval gate test.
- `backend/tests/test_agents_memory.py` (new) — plan→build memory handoff test.

**Acceptance criteria:**
- `POST /api/agents/{id}/plan/approve` is the only way to transition a plan-mode agent to build mode.
- Agent stats endpoint returns at least 4 fields with stable names.
- 6+ new tests pass; 264 existing still pass.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_agents*.py -v
.venv\Scripts\python.exe -m pytest backend/tests -q
```

**Expected parity delta:** **+0.96 weighted points** (Agent modes 72→84, weight 8).
**Risk:** medium (touches the public agent API).
**Time:** 2 days.

---

## #3 — Project config system (Project config: 75 → 88)

**Why:** Per-workspace `agent.config.toml` is parsed but not hot-reloaded, schema validation is silent on errors, and the matrix references a `docs/windows-first-development.md` that does not exist. These are cheap fixes that unblock user-editable project config.

**Files affected:**
- `backend/app/core/project_config.py` — add file-watcher (cross-platform via `watchfiles`) and JSON schema validation with line/column error messages.
- `backend/app/core/config.py` — surface a "config reloaded" event on the event bus.
- `docs/windows-first-development.md` (new) — write the file the matrix references: how to run, how to test, common Windows gotchas (CRLF, backslashes, PowerShell escaping).
- `backend/tests/test_project_config_reload.py` (new) — modify a config file, assert the reload event fires within 1s.
- `backend/tests/test_project_config_schema.py` (new) — feed a malformed config, assert a structured error.

**Acceptance criteria:**
- Modifying `agent.config.toml` while the backend runs triggers a reload event.
- A malformed config produces a structured error with line + column.
- `docs/windows-first-development.md` exists and links to `scripts/validate-local.ps1`, `scripts/check-github-actions.ps1`, and the parity docs.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_project_config*.py -v
```

**Expected parity delta:** **+0.52 weighted points** (Project config 75→88, weight 4).
**Risk:** low.
**Time:** 1 day.

---

## #4 — Ollama model manager UI + provider fallback chain (Model/provider: 62 → 82)

**Why:** The backend API exists for Ollama, but the Web UI cannot pull, list, or delete models, and there is no fallback chain. Both are one-feature-toggles in OpenCode.

**Files affected:**
- `frontend/src/pages/Models.tsx` (new) — list installed models, "pull" button (uses existing `POST /api/providers/ollama/pull`), "delete" button.
- `frontend/src/api/client.ts` — add model manager methods.
- `backend/app/providers/registry.py` — add `fallback_chain: list[str]` to the provider registry config; on primary-provider failure, retry once on the next provider in the chain.
- `backend/tests/test_provider_fallback.py` (new) — primary returns 429, fallback succeeds, telemetry records the fallback.
- `frontend/src/components/NavBar.tsx` — add the "Models" route.

**Acceptance criteria:**
- Models page lists installed Ollama models and supports pull/delete.
- Fallback chain: configure primary=openai, fallback=anthropic, primary returns 429, second call hits anthropic.
- 4+ new backend tests + 1 Playwright e2e test.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_provider_fallback.py -v
pwsh scripts/smoke-providers.ps1
```

**Expected parity delta:** **+0.80 weighted points** (Model/provider 62→82, weight 4).
**Risk:** medium (Web UI addition; new e2e test infrastructure dependency).
**Time:** 2 days.

---

## #5 — Artifact/report/session export (Artifact: 66 → 82)

**Why:** Markdown/JSON export exists, but HTML and PDF do not. The Web UI does not preview artifacts. This is the audit-trail UX gap.

**Files affected:**
- `backend/app/artifacts/exporter.py` — add `to_html(artifact)` and `to_pdf(artifact)` (use `weasyprint` if available, otherwise render-and-screenshot fallback).
- `backend/app/api/artifacts.py` — add `?format=html|pdf` query parameter.
- `frontend/src/components/ArtifactPreview.tsx` (new) — preview pane that uses the existing Markdown renderer + a tables/charts subcomponent.
- `backend/tests/test_artifacts_export.py` (new) — round-trip every format on a sample artifact.

**Acceptance criteria:**
- `GET /api/artifacts/{id}?format=html` returns valid HTML.
- `GET /api/artifacts/{id}?format=pdf` returns valid PDF (or a structured 501 if weasyprint is missing).
- Preview pane renders an artifact without page reload.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_artifacts_export.py -v
.venv\Scripts\python.exe -m ruff check backend/app/artifacts
```

**Expected parity delta:** **+0.64 weighted points** (Artifact 66→82, weight 4).
**Risk:** medium (weasyprint is a native dependency).
**Time:** 2 days.

---

## #6 — Web UI test infrastructure (Web UI: 70 → 85)

**Why:** The Web UI is the **only** major surface with **zero** automated tests. We cannot honestly claim "MOSTLY_COMPLETE" on the Web UI without at least a Playwright smoke + Vitest units + axe a11y. This is also the batch that makes every future Web UI change auditable.

**Files affected:**
- `frontend/package.json` — add `vitest`, `@testing-library/react`, `@playwright/test`, `@axe-core/playwright`; add `test`, `test:e2e`, `test:a11y` scripts.
- `frontend/playwright.config.ts` (new) — single chromium project, baseURL `http://localhost:5173`.
- `frontend/e2e/dashboard.spec.ts` (new) — load Dashboard, assert no console errors, assert at least 1 tool listed.
- `frontend/e2e/permissions.spec.ts` (new) — open the permissions panel, deny a permission, verify the tool is blocked.
- `frontend/src/components/Button.test.tsx` (new) — example Vitest unit.
- `frontend/src/api/sessionSocket.test.ts` (new) — mock the WebSocket, assert the client reconnects.
- `.github/workflows/ci.yml` — add `frontend-test` job.
- `docs/opencode-study/flow-parity-matrix-verified.json` — flip the Web UI category CI flag to true once the test job exists.

**Acceptance criteria:**
- `npm.cmd run test` runs Vitest in <30s.
- `npm.cmd run test:e2e` runs Playwright smoke in <60s.
- `npm.cmd run test:a11y` runs axe on Dashboard + Models + Sessions pages, exits 0.
- New `frontend-test` job in ci.yml passes on `main`.
- ≥ 5 e2e tests, ≥ 3 unit tests, 1 a11y test.

**Validation commands:**
```
cd frontend
npm.cmd run test
npm.cmd run test:e2e
npm.cmd run test:a11y
npm.cmd run build
```

**Expected parity delta:** **+0.90 weighted points** (Web UI 70→85, weight 6).
**Risk:** medium (first test infra = setup cost; weasyprint-style native dep risk does not apply).
**Time:** 3 days.
**Notes:** This is a **prerequisite** for the Web UI consumer updates that batches #1 and #4 will need.

---

## #7 — Memory/compaction real backend (Memory/compaction: 70 → 88)

**Why:** The live health endpoint reports memory as "disabled" because Qdrant is not in the dev compose stack, embeddings are inactive, and there is no load-test that proves compaction triggers. This is the biggest "implemented but not smoke-tested" gap in the audit.

**Files affected:**
- `docker-compose.qdrant.yml` (new) — Qdrant + the backend wired to it.
- `backend/app/memory/embeddings.py` — flip the active flag when Qdrant is reachable; on startup, attempt to connect, log the result.
- `backend/app/memory/compaction.py` — add a `compaction_load_test` that sends N tokens and asserts `compaction_count > 0` at the end.
- `scripts/smoke-memory-qdrant.ps1` (new) — start `docker-compose.qdrant.yml`, run the load test, stop it.
- `scripts/validate-local.ps1` — add `smoke-memory-qdrant` to the smoke phase (gated on Docker).
- `backend/tests/test_memory_load.py` (new) — compact 50k tokens, assert the message count drops.

**Acceptance criteria:**
- `/api/healthz` reports memory status `qdrant-connected` when Qdrant is up, `disabled` when not.
- Load test proves compaction triggers and reconstructs the conversation.
- Smoke passes in `validate-local.ps1 -WithSmokes` when Docker is present.

**Validation commands:**
```
docker compose -f docker-compose.qdrant.yml up -d
.venv\Scripts\python.exe -m pytest backend/tests/test_memory_load.py -v
pwsh scripts/smoke-memory-qdrant.ps1
docker compose -f docker-compose.qdrant.yml down
```

**Expected parity delta:** **+1.08 weighted points** (Memory/compaction 70→88, weight 6).
**Risk:** medium-high (infra; first non-CI docker-compose override).
**Time:** 2 days.

---

## #8 — MCP HTTP/SSE + plugin sandbox (MCP/plugin: 72 → 84)

**Why:** MCP is stdio-only. Plugin sandbox is a thin wrapper that does not isolate on Windows. Both are the audit's stated gaps for this category.

**Files affected:**
- `backend/app/mcp/server_sse.py` (new) — SSE transport mirroring the stdio transport.
- `backend/app/mcp/oauth.py` (new) — minimal OAuth PKCE flow (only for the SSE transport).
- `backend/app/plugins/sandbox.py` — on Windows, use a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; on Linux, use seccomp.
- `backend/app/api/mcp.py` — add `POST /api/mcp/tools/{id}/enable` (bulk) and `DELETE` (bulk disable).
- `backend/tests/test_mcp_sse.py` (new) — round-trip a tool call over SSE.
- `backend/tests/test_plugin_sandbox.py` (new) — fork a plugin that writes to `/etc/passwd`, assert the write fails.

**Acceptance criteria:**
- An MCP server started with `--transport sse` can serve a tool call to the backend.
- A plugin that tries to escape the sandbox fails with a structured error.
- Bulk enable/disable works on a list of tool IDs.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_mcp_sse.py -v
.venv\Scripts\python.exe -m pytest backend/tests/test_plugin_sandbox.py -v
pwsh scripts/smoke-mcp.ps1
```

**Expected parity delta:** **+0.72 weighted points** (MCP/plugin 72→84, weight 6).
**Risk:** medium-high (Windows Job Object API is a new dependency).
**Time:** 3 days.

---

## #9 — CLI/TUI polish + tool system rate limit + CI harden (CLI 80→85, Tools 88→93, CI 78→90)

**Why:** Three small batches that together lift the smaller-weight categories close to ceiling. They are intentionally grouped because they share an audit pattern (low-risk polish that does not change contracts).

**Files affected:**
- `backend/app/cli/repl.py` — slash-command auto-complete; theme switcher.
- `backend/app/tools/registry.py` — per-tool rate limiter (token bucket).
- `backend/app/tools/builtin/read.py` + `bash.py` + `webfetch.py` — semantic truncation (token-aware).
- `.github/workflows/ci.yml` — add `windows-latest-arm64` runner matrix entry.
- `scripts/release-sign.ps1` (new) — sign release artifacts with a self-managed key (deferred unless public release is imminent).

**Acceptance criteria:**
- `/theme dark` and `/theme light` switch the TUI theme live.
- A tool called >N times in 60s returns 429 with a `Retry-After` header.
- Read tool output is truncated to the next 100 tokens, not the next 100 lines.
- `windows-latest-arm64` job in ci.yml passes.

**Validation commands:**
```
.venv\Scripts\python.exe -m pytest backend/tests/test_tool_rate_limit.py -v
.venv\Scripts\python.exe -m pytest backend/tests/test_tool_truncation.py -v
pwsh scripts/smoke-cli.ps1
pwsh scripts/check-github-actions.ps1 -HeadSha <head> -Timeout 600
```

**Expected parity delta:** **+1.48 weighted points** (CLI +0.50, Tools +0.50, CI +0.48).
**Risk:** low to medium.
**Time:** 1.5 days (run in parallel).

---

## Do **NOT** start these until core ≥ 90%

These are explicitly excluded from the core 14-category score. They are listed only so they are not silently dropped:

- **GitHub bot / PR review** (future expansion, weight 18 in a hypothetical full score). Defer until core is ≥ 90% AND a customer asks. A separate deployable.
- **Browser / mobile automation.** Different team / different stack. Defer entirely.
- **Workflow builder.** Different UX paradigm. Defer until design exploration.
- **Cloud providers beyond Ollama/OpenAI/Anthropic** (Bedrock, Vertex, Azure). Only add when paying customer asks.
- **Plugin marketplace / third-party registry.** Needs the plugin sandbox to be solid first.
- **Session replay / cross-process event bus.** Architectural; needs the core event bus to be load-tested first.

---

## Cumulative ROI table (post-verifier-hardening; #1 done, renumbered 2-10 -> 1-9)

| # | Batch | Δ weighted | Days | Δ/day |
| --- | --- | --- | --- | --- |
| ~~1~~ | ~~Fix check-github-actions.ps1 polling~~ | ~~+0.28~~ | ~~0.5~~ | DONE; achieved +0.40 (CI 78 -> 88) |
| 1 (was #1) | File Diff Batch 2 | +0.60 | 2.0 | 0.30 |
| 2 (was #2) | Agent modes polish | +0.96 | 2.0 | 0.48 |
| 3 (was #3) | Project config system | +0.52 | 1.0 | 0.52 |
| 4 (was #4) | Ollama model manager UI | +0.80 | 2.0 | 0.40 |
| 5 (was #5) | Artifact HTML/PDF + preview | +0.64 | 2.0 | 0.32 |
| 6 (was #6) | Web UI test infrastructure | +0.90 | 3.0 | 0.30 |
| 7 (was #7) | Memory/compaction real backend | +1.08 | 2.0 | 0.54 |
| 8 (was #8) | MCP HTTP/SSE + plugin sandbox | +0.72 | 3.0 | 0.24 |
| 9 (was #9) | CLI/TUI polish + tool rate limit + CI harden (CI part mostly done; only ARM64 + signing remain) | +1.08 | 1.5 | 0.72 |
| | **Total remaining** | **+7.30** | **18.5** | 0.39 |
| | **Already shipped in verifier-hardening** | **+0.40** | 0.5 | 0.80 |

After the remaining 9 batches, expected weighted core parity ≈ **79.60 + 7.30 = 86.90%** (close to 90% target; needs ~+3.1 more to land at 90%).

---

## Execution order (single-developer, sequential with #5 parallel after #1)

1. **#1 / was #1** (File Diff Batch 2) — biggest backend contract change; do before #5.
2. **#2 / was #3** (project config) — touches small surface; safe.
3. **#5 / was #6** (Web UI tests) starts in parallel with #1, #3, #4, #6, #7 once #1 lands.
4. **#1 / was #2** (agent modes polish) — public API change.
5. **#3 / was #4** (Ollama manager UI) — needs #5 partially.
6. **#4 / was #5** (artifact export) — independent.
7. **#6 / was #7** (memory real backend) — infra.
8. **#7 / was #8** (MCP HTTP/SSE) — new transport.
9. **#8 / was #9** (CLI/TUI/tools polish + Windows ARM64 + artifact signing) — last because it depends on the categories above being stable.

After the remaining 9 batches, **re-run this audit**. The new scorecard should show ~87% core parity, with the remaining ~13% being the explicitly-deferred future expansion (GitHub bot, browser, mobile, workflow builder) and the final cosmetic polish (theme engine, OAuth PKCE, plugin marketplace).
