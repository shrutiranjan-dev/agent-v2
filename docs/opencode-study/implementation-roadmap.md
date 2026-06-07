# Implementation Roadmap

# CLI/TUI Coding Flow Batch 1 Implementation Result

## Terminal runtime status

- Added `backend.app.cli` as a package with a Typer command surface, preserving the existing `serve` and `migrate` operations.
- Added `health`, `agents`, `sessions list/create/show`, `chat`, `queue status`, `artifacts list`, and `tui` commands.
- Added the `agentv2` console script alias while keeping `agent-platform` compatible.

## API and event client status

- Added a lightweight `httpx` client for existing backend APIs: health, agents, sessions, messages, events, permissions, human input, queue jobs, queue stats, and artifacts.
- Added a `websockets` session event stream client for `/ws/sessions/{session_id}` with reconnect backoff and terminal event stopping.
- The CLI remains a client only; it does not duplicate backend execution logic or bypass `ToolExecutor`.

## Terminal UX status

- Added Rich renderers for health, agents, sessions, queue jobs, artifacts, messages, tool calls, errors, permission prompts, human-input prompts, and event timelines.
- Added terminal permission handlers for approve, deny, and details.
- Added terminal human-input handlers for choices, free text, and cancellation.
- Added diff preview helpers for `write.file`, `edit.file`, and `patch.apply`; if backend metadata does not include a diff, the terminal reports that the diff preview is unavailable instead of inventing one.
- Added a minimal Rich TUI loop for session listing, session creation/opening, agent switching, prompt sending, and queue/session status.

## Smoke and tests

- Added `scripts/cli-tui-smoke.ps1` for deterministic PowerShell validation without requiring model generation.
- Added `backend/tests/test_cli_flow.py` covering API client calls, command parsing, render output, permission approve/deny handlers, human-input answer/cancel handlers, and diff preview extraction.

## Remaining CLI/TUI gaps

- The TUI is intentionally minimal Rich-based Batch 1 rather than a full Textual modal application.
- Live chat depends on the backend worker/model path exactly like the web UI; the deterministic smoke does not claim model generation success.
- Permission diff preview is shown when event/request metadata includes it; richer backend-generated diffs for every mutation tool remain a future polish item.
- Cursor-aware WebSocket replay and full keyboard session switching are future Batch 2 work.

# Immediate P0 tasks

1. Configuration system

   - Why: Permission and model behavior cannot be safely tuned per project without auditable scoped config.
   - Files to change: `backend/app/core/config.py` plus related tests named below.
   - Acceptance criteria: Add environment mode validation and a database-backed settings overlay for permission/model defaults. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_config.py proving production mode rejects default secrets and loads workspace-specific permission defaults.

2. Session model

   - Why: Session lineage, accounting, and tenant safety are incomplete.
   - Files to change: `backend/app/db/models.py` plus related tests named below.
   - Acceptance criteria: Add session lineage/lifecycle fields, enum constraints, and tenant-scoped detail loading. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_sessions.py to prove tenant-isolated detail and persisted model/cost/status transitions.

3. Message model

   - Why: The UI cannot render precise execution timelines or artifacts without ad hoc metadata parsing.
   - Files to change: `backend/app/runtime/message_service.py` plus related tests named below.
   - Acceptance criteria: Introduce Pydantic message-part schemas for assistant, tool, permission, and artifact parts. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_messages.py proving typed parts round-trip and invalid payloads are rejected.

4. Agent run model

   - Why: Long or permission-blocked runs can be lost or require manual re-prompting.
   - Files to change: `backend/app/runtime/agent_runner.py` plus related tests named below.
   - Acceptance criteria: Persist run state transitions and add a resume path invoked by approval or worker scheduling. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_agent_run_resume.py proving a waiting_permission run continues after approve.

5. Tool call model

   - Why: Audit history can show approval while the original tool never executed.
   - Files to change: `backend/app/db/models.py` plus related tests named below.
   - Acceptance criteria: Add FK constraints, normalized status enums, and resume metadata for waiting tool calls. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_tool_call_persistence.py proving permission_request_id references a row and approved calls complete.

6. Event system

   - Why: Multi-container deployments will lose live events for sessions handled by another process.
   - Files to change: `backend/app/runtime/event_bus.py` plus related tests named below.
   - Acceptance criteria: Add typed event schemas and Redis-backed pub/sub while keeping SystemEvent as durable store. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_event_bus.py proving event payload validation and replay after reconnect.

7. WebSocket/realtime events

   - Why: Users can miss permission prompts or tool updates during network blips.
   - Files to change: `frontend/src/stores/eventStore.ts` plus related tests named below.
   - Acceptance criteria: Create typed event store with reconnect/replay and backend cursor replay support. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend event reducer test and backend /sessions/{id}/events replay ordering test.

8. Agent prompts/system instructions

   - Why: The platform may chat but fail to reliably invoke tools for implementation tasks.
   - Files to change: `backend/app/runtime/context_builder.py` plus related tests named below.
   - Acceptance criteria: Build a prompt/context composer with role prompt, guardrails, tool examples, workspace summary, and compacted history. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_context_builder.py proving prompts contain role, allowed tools, protocol examples, and max-step guardrails.

9. Agent runtime loop

   - Why: Production users will see blocked HTTP requests and brittle local model tool behavior.
   - Files to change: `backend/app/runtime/agent_runner.py` plus related tests named below.
   - Acceptance criteria: Refactor into a resumable state machine and queue-backed worker while preserving strict JSON for Ollama tool mode. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_agent_runtime_state_machine.py covering final, tool, permission-wait/resume, max-step, and invalid JSON paths.

10. Agent context building

   - Why: Long sessions become unreliable and local models lose operational context.
   - Files to change: `backend/app/runtime/context_builder.py` plus related tests named below.
   - Acceptance criteria: Create context builder selecting recent messages, summaries, tool results, workspace metadata, and memory snippets under a budget. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_context_builder.py proving long sessions are windowed and summaries/tool outputs are deterministic.

11. File write tool

   - Why: Approved writes can overwrite critical files without diff preview or rollback.
   - Files to change: `backend/app/tools/write.py` plus related tests named below.
   - Acceptance criteria: Add diff preview metadata, atomic write, symlink/secret checks, and approval resume integration. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_write_tool.py proving ask flow, atomic write, and denied secret overwrite.

12. Edit/patch tool

   - Why: Patch application can corrupt files or fail on common diffs.
   - Files to change: `backend/app/tools/patch.py` plus related tests named below.
   - Acceptance criteria: Replace simple parser with a tested patch engine and store before/after diff metadata. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_patch_tool.py with add/update/delete, multi-hunk, context mismatch, and rollback cases.

13. Bash/shell tool

   - Why: Shell execution is the highest-risk tool and currently too broad.
   - Files to change: `backend/app/tools/bash.py` plus related tests named below.
   - Acceptance criteria: Add shell policy with safe parsing, env scrub, cwd enforcement, and explicit exit-code handling. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_bash_tool.py proving destructive deny, external cwd ask, env scrub, and nonzero exit failure.

14. Permission engine

   - Why: Permission prompts are auditable but operationally incomplete.
   - Files to change: `backend/app/permissions/service.py` plus related tests named below.
   - Acceptance criteria: Add saved approval rules and invoke run resume when a request is approved. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_permission_resume.py proving write.file waits, approve resumes, deny fails, and always approval skips future prompts.

15. Permission request/approval flow

   - Why: Users can click Approve and still see the run stuck.
   - Files to change: `backend/app/api/routes_permissions.py` plus related tests named below.
   - Acceptance criteria: Resolve linked tool/run state inside approve/deny and schedule/resume execution. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_permissions_api.py proving approve moves tool_call and agent_run out of waiting_permission.

16. Permission UI integration

   - Why: Users may approve risky operations without enough context or believe approval executed when it did not.
   - Files to change: `frontend/src/pages/Dashboard.tsx` plus related tests named below.
   - Acceptance criteria: Add permission detail cards/modal with input preview and once/always/deny choices tied to backend resume. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend test proving prompt appears from event and approve updates sidecar/tool status.

17. Doom-loop/repeated action protection

   - Why: Repeated harmful variants can still consume resources or mutate state.
   - Files to change: `backend/app/runtime/loop_guard.py` plus related tests named below.
   - Acceptance criteria: Persist loop-guard denials and normalize shell/file inputs before hashing. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_loop_guard.py proving third repeat creates denied ToolCall and audit/system event.

18. External directory protection

   - Why: Some external access can slip through shell commands or symlinks.
   - Files to change: `backend/app/permissions/policy.py` plus related tests named below.
   - Acceptance criteria: Centralize resolved path authority checks and call it from every file and shell tool. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_external_directory.py proving file, patch, glob, grep, and shell workdirs outside workspace ask or deny consistently.

19. Environment/secret file protection

   - Why: Secrets can be read into model prompts, persisted, and displayed in UI.
   - Files to change: `backend/app/permissions/secret_policy.py` plus related tests named below.
   - Acceptance criteria: Implement secret path/content detection and redact sensitive values in tool/model/audit payloads. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_secret_policy.py proving .env/private-key reads ask or deny and outputs are redacted.

20. Audit logging

   - Why: Security investigations will miss who prompted, which model was called, and what data was exposed.
   - Files to change: `backend/app/audit/service.py` plus related tests named below.
   - Acceptance criteria: Centralize audit logging and call it from session, message, model, tool, permission, and artifact services with redaction. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_audit_logs.py proving every tool permission decision and model call writes one redacted audit row.

21. Session detail/chat UI

   - Why: Users may expect safe chat but start a tool-capable session.
   - Files to change: `frontend/src/pages/Dashboard.tsx` plus related tests named below.
   - Acceptance criteria: Create a dedicated chat-safe agent/profile and render structured message/tool/permission parts. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend test proving /models populates dropdown and send payload includes model_name for new/existing chats.

22. Permission prompt UI

   - Why: Users may approve without understanding effect or get stuck after approval.
   - Files to change: `frontend/src/components/PermissionPrompt.tsx` plus related tests named below.
   - Acceptance criteria: Add reusable permission prompt component with preview, risk labels, and once/always/deny actions. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend PermissionPrompt test covering approve, deny, duplicate-click disabled state, and risk preview.

23. Testing coverage

   - Why: Core agent safety regressions can ship unnoticed.
   - Files to change: `backend/tests/test_permission_resume.py` plus related tests named below.
   - Acceptance criteria: Add high-risk integration tests first: permission resume, mutation tools, context builder, migrations, and frontend chat model picker. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: The new tests plus dockerized smoke-test must pass before implementation work continues.

24. Security model

   - Why: Anyone with backend network access can create sessions and run ask-approved tools.
   - Files to change: `backend/app/core/security.py` plus related tests named below.
   - Acceptance criteria: Add local auth/token model and enforce tenant ownership in every route before services run. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_security.py proving unauthenticated access is rejected in production mode and cross-tenant IDs return 404/403.

25. Production-readiness

   - Why: Calling it production-ready now would overstate maturity and create operational/security risk.
   - Files to change: `docs/opencode-study/implementation-roadmap.md` plus related tests named below.
   - Acceptance criteria: Execute the P0 roadmap before adding new feature surface area. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Full docker smoke test plus backend integration suite must prove health, auth, permission resume, tool audit, and chat/tool flows.

# P1 tasks

1. Project/workspace structure

   - Why: Runs can target the wrong workspace root once multiple workspaces exist.
   - Files to change: `backend/app/api/routes_workspaces.py` plus related tests named below.
   - Acceptance criteria: Add project/workspace list/select routes and require selected workspace context on session creation. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_workspaces.py proving session creation uses the requested workspace root and rejects cross-organization IDs.

2. Server boot lifecycle

   - Why: Containers can report healthy while runtime dependencies are degraded.
   - Files to change: `backend/app/main.py` plus related tests named below.
   - Acceptance criteria: Add startup checks for migrations/dependencies and shutdown hooks for background tasks. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_startup.py using TestClient lifespan to prove failed critical dependencies produce explicit degraded state.

3. API route structure

   - Why: Frontend and future SDK contracts can drift as routes grow.
   - Files to change: `backend/app/api/__init__.py` plus related tests named below.
   - Acceptance criteria: Introduce versioned routers and shared response/error schemas while preserving current aliases. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_api_contract.py validating route envelopes, tenant filtering, and OpenAPI paths.

4. OpenAPI/schema generation

   - Why: A backend change can break the UI without compile-time feedback.
   - Files to change: `frontend/src/api/client.ts` plus related tests named below.
   - Acceptance criteria: Add OpenAPI generation and replace manual wire types with generated or schema-checked types. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add scripts/check-openapi.sh and frontend build validation for generated types.

5. Agent registry

   - Why: Operators cannot tune agents without code changes.
   - Files to change: `backend/app/agents/registry.py` plus related tests named below.
   - Acceptance criteria: Load validated agent overrides from database while retaining safe built-in defaults. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_agent_registry.py proving project-specific override changes model/tools safely.

6. Native agents

   - Why: Local chat can request high-authority tools unless permissions catch every path.
   - Files to change: `backend/app/agents/prompts.py` plus related tests named below.
   - Acceptance criteria: Move prompts into versioned modules/files and reduce general chat tool authority by default. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_agent_permissions.py proving general/chat cannot mutate files unless configured.

7. Agent step limits

   - Why: Agents can stop abruptly without useful recovery guidance.
   - Files to change: `backend/app/runtime/agent_runner.py` plus related tests named below.
   - Acceptance criteria: Emit step events and inject a final-step reminder before the last model call. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_agent_loop.py proving max-step stop persists failure and emits an event.

8. Compaction/summarization

   - Why: Long sessions eventually fail or become incoherent.
   - Files to change: `backend/app/runtime/compaction_service.py` plus related tests named below.
   - Acceptance criteria: Implement summary storage and /sessions/{id}/compact without deleting original messages. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_compaction.py proving compact creates summary metadata and later context uses it.

9. Model provider abstraction

   - Why: Even Ollama-only routing needs capabilities and health state for safe model selection.
   - Files to change: `backend/app/providers/base.py` plus related tests named below.
   - Acceptance criteria: Formalize provider capabilities and persist provider/model health snapshots. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_ollama_provider.py proving capability metadata and error normalization.

10. Ollama/local model support

   - Why: Some Ollama tags will chat but fail tool protocol or truncate responses.
   - Files to change: `backend/app/providers/ollama.py` plus related tests named below.
   - Acceptance criteria: Add model capability metadata and separate plain chat mode from strict tool JSON mode. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_ollama_provider.py proving list includes host models and generate supports chat/tool modes.

11. Tool registry

   - Why: Extensibility is blocked until trusted dynamic tool sources are supported.
   - Files to change: `backend/app/tools/registry.py` plus related tests named below.
   - Acceptance criteria: Add reloadable registry providers for plugin/MCP tools while preserving typed Pydantic boundaries. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_tool_registry.py proving duplicate names are rejected and dynamic tools expose schemas safely.

12. Tool metadata/schema validation

   - Why: Local models receive sparse tool guidance and call tools incorrectly.
   - Files to change: `backend/app/tools/base.py` plus related tests named below.
   - Acceptance criteria: Add schema_version/examples and standardize invalid input feedback. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_tool_registry.py proving every tool has examples, schema_version, and valid JSON schema.

13. File read tool

   - Why: Symlink or secret file paths can expose data unexpectedly.
   - Files to change: `backend/app/tools/read.py` plus related tests named below.
   - Acceptance criteria: Add secret path detection and symlink escape checks before reading. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_read_tool.py proving symlink escape asks/denies and .env-like files require approval.

14. Todo tool

   - Why: Users cannot trust todo state as a runtime planning artifact.
   - Files to change: `backend/app/runtime/todo_service.py` plus related tests named below.
   - Acceptance criteria: Persist latest todo list per session and expose it in session detail. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_todo_tool.py proving todo.write updates durable session todo state.

15. Question/human input tool

   - Why: Agents that ask clarifying questions cannot receive answers through the runtime.
   - Files to change: `backend/app/runtime/question_service.py` plus related tests named below.
   - Acceptance criteria: Implement question lifecycle parallel to permission requests with answer resume. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_question_flow.py proving question.ask pauses and resumes with a user answer.

16. Storage/database schema

   - Why: Integrity bugs can appear under concurrent and multi-tenant usage.
   - Files to change: `backend/app/db/migrations/versions/202606050002_integrity_constraints.py` plus related tests named below.
   - Acceptance criteria: Add constraints, FK links, enums/checks, and tenant-aware indexes. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_db_integrity.py proving invalid statuses and orphan permission tool_call IDs are rejected.

17. Migrations

   - Why: Future schema changes can drift silently from SQLAlchemy models.
   - Files to change: `backend/tests/test_migrations.py` plus related tests named below.
   - Acceptance criteria: Add migration smoke tests and model-vs-migration drift checks. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_migrations.py proving upgrade head on empty Postgres and expected tables/constraints exist.

18. Artifact storage

   - Why: Large outputs and generated files remain trapped in text or local filesystem.
   - Files to change: `backend/app/artifacts/artifact_service.py` plus related tests named below.
   - Acceptance criteria: Implement MinIO put/get/presign and persist ToolResult.artifacts from ToolExecutor. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_artifacts.py proving artifact upload, persistence, list, and download.

19. Queue/worker runtime

   - Why: Runs cannot survive restarts or scale horizontally.
   - Files to change: `backend/app/queue/worker.py` plus related tests named below.
   - Acceptance criteria: Move agent execution into Redis-backed worker with locks and resumable jobs. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_worker_runtime.py proving enqueue, worker execution, retry, and permission resume.

20. Web UI dashboard

   - Why: Feature growth will make the UI hard to maintain.
   - Files to change: `frontend/src/pages/Dashboard.tsx` plus related tests named below.
   - Acceptance criteria: Split Dashboard into page components and shared stores before adding more runtime UI. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend component tests proving each tab renders with mocked API data.

21. Model status UI

   - Why: Users cannot tell which models are tool-capable or currently reachable beyond dependency health.
   - Files to change: `frontend/src/pages/Dashboard.tsx` plus related tests named below.
   - Acceptance criteria: Add model detail labels from provider capability metadata without filtering selectable Ollama tags. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend model UI test proving cloud/local tags appear and selected model is sent unchanged.

22. Logs/events UI

   - Why: Operators cannot quickly diagnose failed runs in production.
   - Files to change: `frontend/src/pages/EventsPage.tsx` plus related tests named below.
   - Acceptance criteria: Split events page with filters, detail drawer, and correlation IDs. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend EventsPage test proving severity/type filters and payload detail toggle.

23. Docker/dependency orchestration

   - Why: Developers may mistake dev Compose for production deployment.
   - Files to change: `docker-compose.yml` plus related tests named below.
   - Acceptance criteria: Add dev/production compose profiles and a worker service once queue runtime exists. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend scripts/smoke-test.sh proving compose health and host Ollama routing with docker profile disabled.

24. Health checks

   - Why: Orchestrators can route traffic to an app whose dependencies are degraded.
   - Files to change: `backend/app/api/routes_health.py` plus related tests named below.
   - Acceptance criteria: Add /health/live and /health/ready with migration/dependency readiness and sanitized output. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Extend backend/tests/test_health.py proving ready is degraded when a dependency mock fails.

# P2 tasks

1. Grep/search tool

   - Why: Large repositories can make search slow or noisy.
   - Files to change: `backend/app/tools/grep.py` plus related tests named below.
   - Acceptance criteria: Normalize regex errors and add include/exclude/gitignore options. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_grep_tool.py proving rg and fallback paths return identical bounded results.

2. Glob tool

   - Why: Models can miss files or scan too much in large workspaces.
   - Files to change: `backend/app/tools/glob.py` plus related tests named below.
   - Acceptance criteria: Define glob semantics and ignore behavior matching platform expectations. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_glob_tool.py proving recursive patterns, hidden files, and result truncation.

3. Memory/vector storage

   - Why: Memory infrastructure exists but agents cannot use it.
   - Files to change: `backend/app/memory/memory_service.py` plus related tests named below.
   - Acceptance criteria: Implement memory ingestion/retrieval and inject snippets into context builder. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_memory_service.py proving memory insert, vector search mock, and context retrieval.

4. Graph storage

   - Why: Graph service consumes resources without platform behavior.
   - Files to change: `backend/app/memory/graph_store.py` plus related tests named below.
   - Acceptance criteria: Define graph nodes and relationships for projects, files, symbols, sessions, tools, and workflows. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_graph_store.py proving health, upsert, and traversal with mocked Neo4j session.

5. ClickHouse/event analytics

   - Why: Observability promises are not fulfilled and system_events may grow without analytics offload.
   - Files to change: `backend/app/analytics/event_writer.py` plus related tests named below.
   - Acceptance criteria: Define ClickHouse event table and mirror SystemEvent rows asynchronously. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_event_writer.py proving event_writer serializes SystemEvent to ClickHouse insert payload.

6. Plugin system

   - Why: Unsafe plugin execution would be a critical vulnerability if added casually.
   - Files to change: `backend/app/plugins/loader.py` plus related tests named below.
   - Acceptance criteria: Define plugin manifest and trust model before enabling execution; start with signed/local metadata only. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_plugin_loader.py proving disabled plugins do not load and invalid manifests are rejected.

7. MCP integration

   - Why: Later MCP could bypass permission/audit if not wrapped through ToolExecutor.
   - Files to change: `backend/app/mcp/client.py` plus related tests named below.
   - Acceptance criteria: Implement MCP client with tool discovery feeding ToolRegistry and permission/audit wrapping. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_mcp_registry.py with a fake MCP server exposing one permission-checked tool.

8. CLI client

   - Why: Operators must use HTTP/UI even when UI is down.
   - Files to change: `backend/app/cli.py` plus related tests named below.
   - Acceptance criteria: Add Typer commands for health, models, sessions, send, and permissions. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add backend/tests/test_cli.py using Typer CliRunner for serve config and models/session commands.

9. Agent/tool management UI

   - Why: Operators cannot safely tune runtime without editing code.
   - Files to change: `frontend/src/pages/AgentsPage.tsx` plus related tests named below.
   - Acceptance criteria: Split management pages and add read-only detail drawers before config APIs. Preserve tenant/workspace boundaries and emit audit/system events where applicable.
   - Test required: Add frontend tests proving detail drawers show allowed tools, permission profile, and JSON schema.

# P3 tasks

- No tasks in this priority group.

# P0 Foundation Batch 1 Implementation Result

## Files changed

- `backend/app/core/config.py`
- `backend/app/db/postgres.py`
- `backend/app/db/models.py`
- `backend/app/db/migrations/versions/202606050002_runtime_spine.py`
- `backend/app/core/events.py`
- `backend/app/runtime/event_bus.py`
- `backend/app/api/websocket.py`
- `backend/app/api/routes_sessions.py`
- `backend/app/api/routes_messages.py`
- `backend/app/api/routes_system_events.py`
- `backend/app/runtime/message_parts.py`
- `backend/app/runtime/message_service.py`
- `backend/app/runtime/session_service.py`
- `backend/app/agents/prompts.py`
- `backend/app/agents/build_agent.py`
- `backend/app/agents/plan_agent.py`
- `backend/app/agents/general_agent.py`
- `backend/app/agents/explore_agent.py`
- `backend/app/agents/summary_agent.py`
- `backend/app/agents/compaction_agent.py`
- `backend/app/agents/registry.py`
- `backend/app/runtime/context_builder.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/runtime/loop_guard.py`
- `backend/app/providers/base.py`
- `backend/app/providers/ollama.py`
- `backend/tests/fakes.py`
- `backend/tests/test_config.py`
- `backend/tests/test_context_builder.py`
- `backend/tests/test_db_models.py`
- `backend/tests/test_event_bus.py`
- `backend/tests/test_agent_runner_runtime.py`
- `backend/tests/test_agent_registry.py`
- `backend/tests/test_ollama_provider.py`

## What was implemented

- Added nested Pydantic Settings for app, database, Redis, Qdrant, Neo4j, MinIO, ClickHouse, Ollama, security, runtime limits, and bootstrap tenancy while preserving existing `AP_*` environment variables.
- Added production configuration validation for non-default security secret and non-development database, Neo4j, and MinIO credentials.
- Added runtime ORM/migration fields for tool duration, model call project/workspace scope, system event run/tool linkage, and status/runtime indexes.
- Added typed message part validation for text and tool-result messages.
- Added persisted event envelopes with `event_type`, tenant/session/run/tool IDs, severity, payload, and timestamp.
- Added session WebSocket replay of recent persisted events before live subscription events.
- Split native agent definitions into dedicated modules with explicit prompts, tool allow-lists, permission profile, model config, step limits, temperature/top_p, and hidden flags.
- Added `ContextBuilder` with strict JSON tool-call protocol, allowed tool schemas, recent-message budgeting, summary inclusion, and compaction-needed signaling.
- Updated Ollama provider to use configured timeout and added `/api/chat` support while keeping Ollama-only routing.
- Reworked agent runner to persist model calls, emit run step/model/tool events, use the context builder, reject invalid JSON after one repair attempt, persist tool calls/results, and fail cleanly on max steps.
- Updated tool execution to emit `tool_call.requested`, persist denied/invalid/unknown tool calls, store duration, link events to run/tool IDs, and keep doom-loop protection configurable.

## What remains

- Permission approval still records approve/deny but does not resume paused agent runs.
- Mutation tools still need stronger path/secret protection before production use.
- Model capability metadata is still missing; every Ollama tag is treated as strict-JSON capable.
- Redis pub/sub is not yet wired into the event bus; the current bus is process-local with Postgres persistence.
- Database migration tests still need a real Postgres test container or CI service.
- Frontend permission prompt polishing and session-detail chat UI hardening remain in later P0/P1 work.

## Tests run

- `.venv/bin/pytest backend/tests` passed: 31 tests.
- `.venv/bin/python -m compileall backend/app` passed.
- Ruff was not run because `.venv/bin/ruff` is not installed.

## Known limitations

- Unit tests use fakes for runtime services and do not replace a Postgres migration integration test.
- WebSocket replay is local-process only until Redis pub/sub is integrated.
- Strict JSON mode can fail with models that are good chat models but poor structured-output models; model capability routing remains a follow-up.

# P0 Foundation Batch 2 Implementation Result

## Files changed

- `backend/app/permissions/matcher.py`
- `backend/app/permissions/policy.py`
- `backend/app/permissions/models.py`
- `backend/app/permissions/service.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/runtime/event_bus.py`
- `backend/app/core/config.py`
- `backend/app/core/events.py`
- `backend/app/tools/grep.py`
- `backend/app/tools/glob.py`
- `backend/app/tools/patch.py`
- `backend/app/providers/base.py`
- `backend/app/providers/router.py`
- `backend/app/api/routes_models.py`
- `backend/app/api/routes_permissions.py`
- `.env.example`
- `pyproject.toml`
- `scripts/db-migration-smoke.sh`
- `backend/tests/test_permission_resume.py`
- `backend/tests/test_permissions.py`
- `backend/tests/test_event_bus.py`
- `backend/tests/test_model_capabilities.py`
- `backend/tests/test_migrations_postgres.py`
- `backend/tests/fakes.py`

## What was implemented

- Added one-shot permission lifecycle methods for approve and deny.
- Added secure permission resume validation for pending status, linked tool call, linked run, linked session, tool registration, matching input payload, and matching input hash.
- Approval now executes the stored waiting tool call, writes the tool result message, and continues the same agent run until final, max-steps, failure, or another permission pause.
- Denial now marks the permission request denied, marks the pending tool call denied, marks the run failed, emits permission/tool/run events, and does not execute the tool.
- Added `permission.resume_blocked` security event and audit log path for mismatched or unsafe resume attempts.
- Added secret path policy for `.env`, `.env.*`, `credentials.json`, `secrets.*`, `*secret*`, `*token*`, and `*credential*`, while allowing `.env.example`.
- Added default deny policy for private-key-like paths such as `*.pem`, `*.key`, `id_rsa`, and `id_ed25519`.
- Hardened external directory policy: reads/searches outside workspace ask, writes/edits/patches outside workspace deny by default, and symlink-resolved paths are evaluated.
- Updated grep/glob/patch resource reporting so permission policy sees resolved filesystem paths instead of ambiguous search patterns.
- Added optional Redis pub/sub event path. When `AP_REDIS_PUBSUB_ENABLED=true`, events publish to `session:{session_id}:events`; local in-process mode remains available for tests and single-worker development.
- Added Ollama-only model capability metadata and selection, including JSON-protocol support, disabled models, context window, max output tokens, and per-agent configured model fallback.
- `/models` now returns capability metadata for each local Ollama tag returned by `/api/tags`.
- Added real Postgres migration smoke script and opt-in pytest that skip unless `AP_TEST_POSTGRES_URL` points at a real PostgreSQL database.
- Added Ruff as a test/dev dependency and configured lint to avoid broad pre-existing line-length/FastAPI `Depends` churn.

## Tests run

- Baseline before edits: `.venv/bin/pytest backend/tests` passed with 31 tests.
- Final: `.venv/bin/pytest backend/tests` passed with 46 tests and 1 skipped migration smoke test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- Migration smoke command was skipped because `AP_TEST_POSTGRES_URL` is not set.

## Migration validation command

- Run `AP_TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@host:5432/db scripts/db-migration-smoke.sh`.
- The script runs Alembic `upgrade head`, verifies required runtime tables, and verifies the `vector` extension.
- The pytest equivalent is `AP_TEST_POSTGRES_URL=... .venv/bin/pytest backend/tests/test_migrations_postgres.py`.

## What remains

- Permission UI is still not polished because this batch intentionally avoided frontend work.
- Event bus Redis subscribe path is implemented, but multi-worker deployment still needs operational testing against a live Redis service.
- Secret protection is path-based; content redaction inside model prompts, audit logs, and tool outputs remains a later hardening task.
- Bash command path parsing and environment scrubbing remain P0/P1 security work.
- Real Postgres migration smoke was added but not executed locally because no `AP_TEST_POSTGRES_URL` was provided.

# P0 Foundation Batch 3 Implementation Result

## Files changed

- `backend/app/core/redaction.py`
- `backend/app/runtime/event_bus.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/runtime/session_service.py`
- `backend/app/permissions/policy.py`
- `backend/app/permissions/service.py`
- `backend/app/api/routes_permissions.py`
- `backend/app/providers/ollama.py`
- `backend/app/tools/bash.py`
- `backend/app/tools/read.py`
- `backend/tests/test_bash_safety.py`
- `backend/tests/test_redaction.py`
- `frontend/src/api/client.ts`
- `frontend/src/api/sessionSocket.ts`
- `frontend/src/components/EventStream.tsx`
- `frontend/src/components/MessageList.tsx`
- `frontend/src/components/PermissionPrompt.tsx`
- `frontend/src/components/ToolCallTimeline.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/styles/app.css`
- `scripts/db-migration-smoke.sh`
- `scripts/runtime-smoke.sh`

## What was implemented

- Added a reusable typed frontend API contract for sessions, events, permissions, models, agents, and permission approval/denial responses.
- Added a reconnecting session WebSocket client with status callbacks and parsed runtime events.
- Added shared React components for message timelines, tool-call timelines, event streams, and permission prompts.
- Updated Chat and Sessions views to show live WebSocket status, messages, tool calls, runtime events, and permission prompts with double-click-safe approve/deny handling.
- Added redacted permission payloads for the UI, including `permission_request_id`, tool name, reason, input preview, and linked run/tool IDs.
- Added centralized backend redaction for bearer tokens, env assignments, sensitive JSON keys, private key blocks, and long token-like strings.
- Applied redaction before persisting/sending system events, tool outputs, model call request/response metadata, permission API responses, and session detail responses.
- Hardened bash execution by resolving cwd against workspace root, blocking execution outside the workspace at the tool boundary, scrubbing sensitive env vars from subprocesses, handling timeouts clearly, bounding captured output, and redacting shell output.
- Expanded destructive shell deny patterns for `rm -rf /`, `rm -rf *`, `sudo rm`, `mkfs`, `dd if=`, fork-bomb syntax, shutdown/reboot/poweroff, broad chmod, and recursive chown.
- Added `scripts/runtime-smoke.sh` for live Docker validation of backend health, dependency health, migrations, agents, models, session creation, prompt send, and permission endpoint.
- Fixed `scripts/db-migration-smoke.sh` URL normalization so `postgresql+psycopg://` works for Alembic and psycopg table checks.

## Validation status

- Backend tests: `.venv/bin/pytest backend/tests` passed with 58 tests and 1 skipped real-Postgres opt-in test.
- Compile: `.venv/bin/python -m compileall backend/app` passed.
- Ruff: `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- Frontend build/typecheck: `npm run build` in `frontend/` passed.
- Live Docker runtime smoke: `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/runtime-smoke.sh` passed against the running Compose stack.

## Remaining gaps

- Redis pub/sub was live dependency-checked through backend health, but multi-worker WebSocket fanout still needs a two-backend operational test.
- Permission resume still runs inline in the approval request; queue-backed resume remains future worker work.
- Bash policy is safer, but complex shell parsing can still miss intent hidden behind scripts or shell functions.
- Redaction is pattern-based and should be expanded with configurable organization policy and regression fixtures as new leak classes are discovered.
- Frontend has build/type coverage only; component/unit tests should be added once a test runner is introduced.

# P0 Foundation Batch 4 Implementation Result

## Files changed

- `backend/app/core/config.py`
- `backend/app/core/events.py`
- `backend/app/queue/jobs.py`
- `backend/app/queue/worker.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/permissions/service.py`
- `backend/app/api/routes_messages.py`
- `backend/app/api/routes_permissions.py`
- `backend/tests/test_queue_jobs.py`
- `docker-compose.yml`
- `.env.example`
- `pyproject.toml`
- `frontend/src/api/client.ts`
- `frontend/src/styles/app.css`
- `scripts/runtime-smoke.sh`
- `scripts/redis-fanout-smoke.sh`

## What was implemented

- Added queue configuration with `AP_QUEUE_ENABLED`, Redis queue names, retry/dead-letter limits, polling timeout, and retry backoff.
- Added a production guard in `backend/app/core/config.py`: `APP_ENV=production` now fails validation if queue execution is disabled.
- Added `backend/app/queue/jobs.py` with typed Redis job envelopes for `agent_run` and `permission_resume`, enqueue helpers, dequeue handling, retry, dead-letter, and job failure event emission.
- Replaced the worker entrypoint in `backend/app/queue/worker.py` with a standalone queue worker that claims Redis jobs, executes agent runs/resumes, emits worker lifecycle events, and shuts down on SIGTERM/SIGINT.
- Updated session message handling so `POST /sessions/{id}/messages` creates a queued agent run and enqueues work when queue mode is enabled; development inline fallback remains available when queue mode is disabled.
- Updated permission approval so approved pending requests enqueue a permission resume job when queue mode is enabled; development inline fallback remains available when queue mode is disabled.
- Added queue/run events: `agent_run.queued`, `agent_run.resume_queued`, `agent_run.resumed`, `agent_run.blocked`, `worker.started`, `worker.stopped`, `worker.job.failed`, and `worker.job.dead_lettered`.
- Added `backend-worker` to `docker-compose.yml` using the same backend image and `python -m backend.app.queue.worker`.
- Updated the frontend API response types and status styling so queued, resumed, resume queued, and blocked states do not render as unknown/failure states.
- Added `scripts/redis-fanout-smoke.sh` to validate Redis channel naming, publish, subscribe, and WebSocket delivery through the active backend.
- Updated `scripts/runtime-smoke.sh` to exercise the queued worker path, wait for queued/running/resume states, prefer small local Ollama models, and fail loudly when a queued run does not complete.

## Validation status

- Backend tests: `.venv/bin/pytest backend/tests` passed with 66 tests and 1 skipped real-Postgres opt-in test.
- Compile: `.venv/bin/python -m compileall backend/app` passed.
- Ruff: `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- Frontend build/typecheck: `npm run build` in `frontend/` passed.
- Docker Compose validation: `docker compose config` passed.
- Live Docker runtime smoke: `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/runtime-smoke.sh` passed against the running Compose stack, backend worker, Redis, Postgres, and host Ollama using `llama3.2:3b`.
- Redis fanout smoke: `scripts/redis-fanout-smoke.sh` passed for Redis connection, `session:{session_id}:events` channel naming, publish, subscribe, and WebSocket delivery.

## Remaining gaps

- `scripts/redis-fanout-smoke.sh` does not prove true two-backend fanout; it proves Redis-backed WebSocket delivery through the active backend. A future Compose profile should launch two API replicas and assert a publish from one process is delivered by another.
- Queue job state is represented through Redis payloads, system events, and run/session status. A durable `queue_jobs` database table would improve replay, dashboards, and operator visibility.
- Queue retry/dead-letter behavior is unit-tested, but the live smoke currently exercises the successful path only.
- Agent execution is queue-backed, but no separate autoscaling or worker concurrency controls exist yet.
- Permission denial remains inline because it does not execute work; that is acceptable for this batch but should still be represented consistently in future operator dashboards.

# P0 Foundation Batch 5 Implementation Result

## Files changed

- `backend/app/core/config.py`
- `backend/app/core/events.py`
- `backend/app/db/models.py`
- `backend/app/db/migrations/versions/202606050003_queue_jobs.py`
- `backend/app/queue/jobs.py`
- `backend/app/queue/worker.py`
- `backend/app/api/routes_messages.py`
- `backend/app/api/routes_permissions.py`
- `backend/tests/test_db_models.py`
- `backend/tests/test_migrations_postgres.py`
- `backend/tests/test_queue_jobs.py`
- `docker-compose.yml`
- `.env.example`
- `scripts/db-migration-smoke.sh`
- `scripts/permission-resume-smoke.sh`
- `scripts/redis-fanout-smoke.sh`

## Durable queue job status

- Added a `queue_jobs` table with UUID primary key, job type, status, priority, run/session/permission/message links, JSONB payload, unique idempotency key, attempt counters, worker claim metadata, availability time, completion/failure timestamps, and last error.
- Added indexes for `(status, available_at)`, idempotency, session, run, permission request, and job type.
- Redis queue messages now carry only `queue_job_id`; trusted execution payloads are loaded from Postgres.
- Migration `202606050003_queue_jobs.py` creates the table and indexes, and migration smoke now verifies `queue_jobs` exists.

## Idempotency status

- Agent run enqueue idempotency key: `agent_run:{session_id}:{user_message_id}:{agent_id}`.
- Permission resume enqueue idempotency key: `permission_resume:{permission_request_id}`.
- Duplicate durable enqueue returns the existing `queue_jobs` row.
- Duplicate Redis wake-up messages are deduped by DB state: completed, dead-lettered, or cancelled jobs are ignored by workers.

## Concurrency status

- Worker IDs are generated from hostname and process id, with `AP_QUEUE_WORKER_ID` override support.
- Workers must atomically claim a durable job before execution.
- Claim transitions support `queued -> claimed -> running -> completed`.
- Failed jobs transition to retryable `queued` with `available_at`, or `dead_letter` after max attempts.
- Stale `claimed`/`running` jobs can be reclaimed after `AP_QUEUE_VISIBILITY_TIMEOUT_SECONDS`.
- Unit coverage proves two workers cannot claim the same fresh job, stale jobs can be reclaimed, completed jobs do not rerun from duplicate Redis messages, and max attempts dead-letter the job.

## Permission resume smoke status

- Added `scripts/permission-resume-smoke.sh`.
- The smoke creates a normal session through the API, seeds a realistic pending `write.file` permission in the test database, approves it through `POST /permissions/{id}/approve`, verifies the response returns `resume_queued`, waits for the worker to execute the approved tool, verifies the file write, verifies exactly one `tool_call.completed`, and verifies `permission.approved`, `agent_run.resume_queued`, `agent_run.resumed`, and `tool_call.completed` events.
- Live result: `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/permission-resume-smoke.sh` passed.

## Two-backend fanout status

- Updated `scripts/redis-fanout-smoke.sh`.
- The script still validates direct Redis publish/subscribe/WebSocket delivery.
- It now also starts a second backend process on a separate port, connects WebSocket to backend B, triggers `message.created` through backend A, and requires backend B to receive that event through Redis.
- Live result: `TRUE_TWO_BACKEND_FANOUT=passed`.

## Tests run

- `.venv/bin/pytest backend/tests` passed with 71 tests and 1 skipped real-Postgres opt-in test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- `npm run build` in `frontend/` passed.
- `docker compose config` passed.
- `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/runtime-smoke.sh` passed.
- `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/permission-resume-smoke.sh` passed.
- `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/redis-fanout-smoke.sh` passed with `TRUE_TWO_BACKEND_FANOUT=passed`.

## Remaining gaps

- There is no operator-facing queue jobs API or dashboard view yet.
- Worker concurrency is safe for claiming, but there is no configurable multi-coroutine worker pool inside one worker process.
- Queue retry/dead-letter live smoke is not implemented; it is covered by unit tests only.
- Queue job rows do not yet record locked worker heartbeat updates during very long model/tool execution.
- Permission resume smoke uses deterministic DB seeding to avoid model-prompt unreliability; a future end-to-end model-created permission prompt smoke can be added once local model tool-call reliability is stronger.

# Tool System Parity Batch 1 Implementation Result

## Files changed

- `backend/app/tools/base.py`
- `backend/app/tools/registry.py`
- `backend/app/tools/__init__.py`
- `backend/app/tools/read.py`
- `backend/app/tools/write.py`
- `backend/app/tools/edit.py`
- `backend/app/tools/patch.py`
- `backend/app/tools/grep.py`
- `backend/app/tools/glob.py`
- `backend/app/tools/bash.py`
- `backend/app/tools/todo.py`
- `backend/app/tools/question.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/core/events.py`
- `backend/tests/test_tool_registry.py`
- `backend/tests/test_tool_parity.py`
- `backend/tests/test_redaction.py`

## Tools implemented or polished

- Added formal native tool metadata: name, title, description, category, schemas, permission key, risk level, workspace/artifact flags, timeout, max output, examples, and enabled status.
- Added a unified `ToolResult` contract with `ok`, structured error object, artifacts, metadata, redaction/truncation flags, timestamps, and duration.
- Updated `ToolExecutor` persistence so successful and failed tool outputs are stored as normalized JSON-safe `ToolResult` payloads.
- Updated disabled-tool handling so the registry refuses disabled tools unless `include_disabled=true` is explicitly requested.
- Reworked `read.file` for workspace path resolution, symlink safety, line ranges, byte caps, optional line numbers, binary refusal, encoding fallback, and redacted structured output.
- Reworked `write.file` for workspace-only writes, optional parent creation, backup-on-overwrite, expected hash guard, atomic temp-file write, fsync, and hash/byte metadata.
- Reworked `edit.file` for exact replacement, range replacement, ambiguity refusal, dry-run diff previews, hash guard, and atomic writes.
- Reworked `patch.apply` for internal patch support, unified diff validation/application, dry-run mode, binary patch refusal, workspace path validation, and changed-file stats.
- Reworked `grep.search` for literal/regex modes, include/exclude globs, case sensitivity, max matches/files, context lines, binary skipping, and secret-file omission.
- Reworked `glob.search` for rooted globbing, hidden-file control, exclude patterns, max results, files/directories/both filtering, stable sorting, and outside-symlink blocking.
- Polished `bash.run` with a structured command classifier, destructive command refusal result, cwd resolution, output truncation metadata, redaction flags, and exit status metadata.
- Reworked `todo.write` as a session-scoped todo contract and persisted todo updates into session metadata through the executor side effect.
- Polished `question.ask` metadata and emitted `question.requested` events with structured question payloads.
- Removed an eager `backend.app.tools` package-level registry import that created a policy/tool circular import risk.

## Safety behavior

- Workspace-relative and absolute file paths resolve through real paths before tool execution.
- Reads refuse binary content instead of leaking bytes into model context.
- Writes and edits use stale-hash guards where supplied and avoid partial writes through atomic replace.
- Grep omits files that default policy would ask/deny for `read.file`, preventing secret content from leaking in search results.
- Glob detects symlinks resolving outside the workspace and counts them as blocked.
- Bash uses the central destructive-shell policy and returns a structured denial for blocked commands.
- Tool outputs persisted by `ToolExecutor` are redacted and JSON serialized before storage/events.

## Tests run

- `.venv/bin/pytest backend/tests` passed with 81 tests and 1 skipped real-Postgres opt-in test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.

## Remaining tool parity gaps

- `question.ask` durable lifecycle was still partial at the end of Batch 1; Batch 2 below closes the durable request, answer/cancel, timeout, UI, and queue-backed resume path.
- `todo.write` persists todos in `sessions.metadata_json`; a dedicated table would be better for multi-user auditability and item history.
- Patch support is safe and tested for common text diffs, but complex multi-hunk transformations are still thinner than a mature patch engine.
- Grep is implemented in Python for portability; a future `rg` backend could improve performance on very large workspaces while preserving the same result contract.
- Tool artifact support is represented in metadata but no native tool in this batch produces MinIO-backed artifacts.
- `/tools` now exposes full metadata, but there is no separate generated tool documentation page or frontend metadata polish in this batch.

# Tool System Parity Batch 2 Implementation Result

## Files changed

- `backend/app/db/models.py`
- `backend/app/db/migrations/versions/202606050004_human_input_requests.py`
- `backend/app/core/config.py`
- `backend/app/core/events.py`
- `backend/app/tools/question.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/runtime/human_input_service.py`
- `backend/app/queue/jobs.py`
- `backend/app/api/routes_human_input.py`
- `backend/app/main.py`
- `backend/tests/test_human_input.py`
- `backend/tests/test_db_models.py`
- `backend/tests/test_migrations_postgres.py`
- `frontend/src/api/client.ts`
- `frontend/src/components/HumanInputPrompt.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/styles/app.css`
- `docker-compose.yml`
- `scripts/db-migration-smoke.sh`
- `scripts/human-input-smoke.sh`

## Human input persistence

- Added durable `human_input_requests` with session/run/tool-call boundaries, status, answer fields, expiry, request hash, details JSONB, metadata JSONB, and indexes.
- Added `human_input_request_id` to `queue_jobs` so human-input resume jobs are durable and idempotent.
- Migration smoke now verifies `human_input_requests` exists.

## Answer and resume behavior

- `question.ask` now uses the single-question contract: `question`, `details`, `timeout_seconds`, `choices`, and `allow_free_text`; it still accepts the previous `questions: [...]` shape for compatibility.
- `ToolExecutor` parks `question.ask` calls with `tool_calls.status=waiting_human_input`, creates a durable human input request, emits `question.requested`, and returns a pause outcome.
- `AgentRunner` marks runs/sessions as `waiting_human_input`, emits `agent_run.waiting_human_input`, and resumes from answered human input through a completed `question.ask` tool result.
- Added `human_input_resume` queue jobs with idempotency key `human_input_resume:{human_input_request_id}`.
- Worker dispatch now loads answered requests, validates hashes/tool/run/session linkage, completes the pending `question.ask` tool call, writes a tool-result message, emits `agent_run.resumed_from_human_input`, and continues the agent loop.

## API and frontend status

- Added `GET /human-input/requests`, `POST /human-input/{id}/answer`, and `POST /human-input/{id}/cancel`.
- Answer validates pending status, expiry, choices, and double-submit protection; queue mode returns `resume_queued`.
- Cancel marks the request/tool/run/session as cancelled and emits blocked/failure events without executing any tool.
- Added `HumanInputPrompt` UI with choice buttons, optional free text, answer/cancel loading states, and separate display from permission prompts in Chat and Session Detail.
- WebSocket events refresh human-input prompts the same way permission prompts refresh.

## Timeout and cancel behavior

- Answering an expired request marks it `expired`, emits `question.expired`, blocks the run, and rejects the answer.
- `human_input_service.expire_pending` can expire old pending requests without adding a scheduler yet.
- Cancellation is explicit and irreversible; cancelled requests cannot later be answered.

## Smoke status

- Added `scripts/human-input-smoke.sh`.
- Smoke uses a guarded test-only seed endpoint requiring `AP_ENABLE_TEST_ENDPOINTS=true` and `APP_ENV!=production`; production config rejects enabled test endpoints.
- The smoke validates session creation, deterministic `question.ask` pending state, answer API, queued resume, worker resume, exactly one completed question tool call, and required events.
- Current shell result: smoke did not run because `AP_TEST_POSTGRES_URL`/`AP_DATABASE_URL` is not set. Required command:
  `AP_ENABLE_TEST_ENDPOINTS=true AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/human-input-smoke.sh`

## Tests run

- `.venv/bin/pytest backend/tests` passed with 89 tests and 1 skipped real-Postgres opt-in test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- `npm run build` in `frontend/` passed.
- `docker compose config` passed.
- `scripts/human-input-smoke.sh` and `scripts/permission-resume-smoke.sh` both failed fast in this shell because no Postgres test URL was configured.

## Remaining tool/runtime gaps

- Human-input live smoke is implemented but not executed in this shell due missing external DB URL.
- The guarded smoke seed endpoint is intentionally test-only; a model-driven question prompt smoke remains future work once local model tool-call reliability is stronger.
- There is no frontend history view for answered/cancelled/expired human-input requests yet; the UI shows pending prompts and event history.
- No periodic scheduler exists for expiry; expiry is enforced on answer and available through `expire_pending`.

# Memory + Compaction Parity Batch 1 Implementation Result

## Files changed

- `backend/app/db/models.py`
- `backend/app/db/migrations/versions/202606050005_memory_compaction.py`
- `backend/app/core/config.py`
- `backend/app/core/events.py`
- `backend/app/providers/base.py`
- `backend/app/providers/ollama.py`
- `backend/app/memory/summary_service.py`
- `backend/app/memory/memory_service.py`
- `backend/app/memory/pgvector_store.py`
- `backend/app/memory/qdrant_store.py`
- `backend/app/runtime/context_builder.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/queue/jobs.py`
- `backend/app/api/routes_memory.py`
- `backend/app/runtime/session_service.py`
- `backend/app/main.py`
- `backend/tests/test_memory_compaction.py`
- `backend/tests/test_db_models.py`
- `backend/tests/test_migrations_postgres.py`
- `frontend/src/api/client.ts`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/styles/app.css`
- `scripts/db-migration-smoke.sh`
- `scripts/memory-compaction-smoke.sh`

## DB schema status

- Added durable `session_summaries` with session/run links, summary type, source message range, message count, token estimate, char count, model, active/superseded/failed status, metadata JSONB, timestamps, and indexes.
- Upgraded `memory_items` with `source_type`, `source_id`, scoped `content_hash`, `embedding_model`, `visibility`, `status`, and additional query indexes.
- Added a pgvector ivfflat index when the `vector` extension is installed; migrations do not require Qdrant.
- Migration smoke now verifies `session_summaries` and `memory_items` alongside existing runtime tables.

## Summary service status

- Added `summary_service` for active summary creation, latest/fetch, superseding active summaries, failed summary recording, size estimates, redaction, and events.
- Events added: `summary.created`, `summary.failed`, and `summary.superseded`.
- Failed model summary attempts create a failed `session_summaries` row instead of corrupting active context.

## Memory service status

- Added `memory_service` for scoped memory creation, content-hash dedupe, text fallback retrieval, visibility filtering, and summary-to-memory creation.
- Embeddings are explicitly disabled by default and recorded as `embedding_status=disabled`; no fake vectors are generated.
- Added Ollama embedding method for future enabled embeddings.
- Qdrant store now reports degraded when disabled and has a real upsert path when enabled/configured.

## Compaction agent status

- Hidden `summary` and `compaction` agents remain tool-restricted with no arbitrary tools.
- Added `AgentRunner.create_session_summary` for manual/model summaries.
- Added `AgentRunner.run_compaction_job` for queue-backed compaction, summary persistence, memory item creation, and `compaction.started/completed/failed` events.
- Model failures record `summary.failed` and do not fail the user-facing agent run.

## Context builder behavior

- Context now includes active durable summaries first, relevant memory second, and recent messages last within the existing character budget.
- Context returns `included_summaries`, `included_memory_items`, `budget_used`, and `compaction_reason`.
- Old messages remain excluded under pressure; the builder never dumps unbounded history.
- Normal user runs emit `compaction.needed` when pressure is detected and enqueue `session_compaction` when the runtime queue is enabled.

## API and UI status

- Added `GET /sessions/{id}/summaries`, `POST /sessions/{id}/summaries`, `GET /memory/items`, `POST /memory/items`, and `GET /sessions/{id}/memory`.
- Session detail now includes active summaries for the UI.
- Session detail UI displays a compact â€œSession summariesâ€ panel without disrupting the existing chat/tool/permission layout.

## Smoke status

- Added `scripts/memory-compaction-smoke.sh`.
- Smoke uses a guarded non-production test seed requiring `AP_ENABLE_TEST_ENDPOINTS=true`, `AP_QUEUE_ENABLED=true`, and a real Postgres URL.
- The smoke validates backend health, Postgres/Redis dependency health, queued worker compaction, active summary creation, session-summary memory creation, and required events.
- Current shell result: smoke did not run because `AP_TEST_POSTGRES_URL`/`AP_DATABASE_URL` is not set.

## Tests run

- `.venv/bin/pytest backend/tests` passed with 99 tests and 1 skipped real-Postgres opt-in test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- `npm run build` in `frontend/` passed.
- `docker compose config` passed.
- `scripts/memory-compaction-smoke.sh`, `scripts/human-input-smoke.sh`, and `scripts/permission-resume-smoke.sh` all failed fast in this shell because no Postgres test URL was configured.

## Remaining memory/compaction gaps

- Live memory compaction smoke is implemented but not executed in this shell due missing external DB URL.
- Embedding generation is disabled by default; enabling it requires an Ollama embedding model and real vector-dimension validation.
- Qdrant is degraded by default and not used unless explicitly configured.
- There is no periodic background scheduler for compaction; compaction is queued when context pressure is detected during a run or through the guarded smoke endpoint.
- Summary quality is model-dependent; failed summaries are safely recorded but not auto-retried outside the queue job retry policy.

# Code Intelligence + LSP Parity Batch 1 Implementation Result

## DB schema status

- Added `code_files`, `code_symbols`, `code_references`, and `code_diagnostics` ORM models with UUID primary keys, workspace/project scoping, JSONB metadata, timestamps, and query indexes.
- Added Alembic migration `202606050006_code_intelligence.py` and updated migration smoke checks for the new tables.
- Migration remains Postgres-first and does not introduce SQLite or local JSON state.

## Indexer status

- Added `backend/app/codeintel/indexer.py` with workspace-rooted scanning, extension-based language detection, SHA-256 change detection, unchanged-file skipping, secret-path exclusion, symlink/outside-root protection, and excluded directory patterns.
- Added static parsers for Python via `ast`, TypeScript/JavaScript via regex fallback, and Markdown headings.
- Added events `code_index.started`, `code_index.file_indexed`, `code_index.completed`, and `code_index.failed`.

## Diagnostics status

- Added `backend/app/codeintel/diagnostics.py` with ruff-line parsing and structured diagnostic ingestion.
- Diagnostics are normalized into `code_diagnostics` and can be listed by workspace/file/severity.
- Tool-driven lint command execution is not added in this batch; diagnostics command runners remain degraded/manual-ingestion mode.

## LSP status

- Added `backend/app/codeintel/lsp_client.py` with an explicit static database fallback for definitions, references, document symbols, and diagnostics.
- Real LSP server process management is not claimed or enabled in this batch; `/health/codeintel` reports degraded static fallback status.

## Tools added

- Added registered native tools: `code.index`, `code.symbols`, `code.definition`, `code.references`, `code.diagnostics`, and `code.map`.
- Tools use the existing audited `ToolExecutor`, permission policy, `ToolContext`, and normalized `ToolResult` shape.
- Native read-oriented agents now receive code-intelligence tools without granting additional write permission.

## API and UI status

- Added API routes: `POST /code/index`, `GET /code/files`, `GET /code/symbols`, `GET /code/definition`, `GET /code/references`, `GET /code/diagnostics`, `GET /code/map`, and `GET /health/codeintel`.
- Context builder now includes bounded code map, relevant symbols, and error diagnostics without injecting full source files.
- Dashboard includes a `Code` section with index status, LSP status, file/symbol/reference/diagnostic counts, symbol search, diagnostics, language counts, and top files.

## Tests run

- `.venv/bin/pytest backend/tests` passed with 109 tests and 1 skipped real-Postgres opt-in test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- `npm run build` in `frontend/` passed.
- `docker compose config` passed.

## Smoke result

- Added `scripts/codeintel-smoke.sh`.
- Current shell result: failed against `http://localhost:8000` because a stale live backend returned 404 for `GET /health/codeintel`; restart/rebuild the backend before rerunning the smoke.
- Existing `scripts/memory-compaction-smoke.sh` still requires `AP_TEST_POSTGRES_URL` or `AP_DATABASE_URL` to validate Docker-backed compaction.

## Remaining gaps

- Real JSON-RPC LSP process lifecycle is still future work.
- Diagnostics command runners for ruff/mypy/TypeScript are not wired into a safe scheduled/runtime flow yet.
- Code references are static/import/call fallback quality, not semantic LSP-grade references.
- No queue-backed background indexing job exists yet; indexing is synchronous through API/tool invocation.
- Code map memory is high-level only; embeddings/vectorization remain disabled unless configured later.

# MCP + Plugin System Parity Batch 1 Implementation Result

## DB schema status

- Added migration `202606050007_mcp_plugins.py` to upgrade `mcp_servers` and `plugins` with project/workspace scope, enabled/trusted/status fields, redacted-env-ready JSONB metadata, and lifecycle timestamps.
- Added durable `mcp_tools` and `plugin_tools` tables with scoped full names such as `mcp.server.tool` and `plugin.plugin.tool`, JSON schemas, risk levels, and disabled-by-default flags.
- Updated ORM mappings in `backend/app/db/models.py`; no SQLite or JSON-file state was introduced.

## MCP lifecycle status

- Added `backend/app/mcp/client.py`, `backend/app/mcp/service.py`, and `backend/app/mcp/tools.py`.
- MCP servers can be created, enabled/disabled, connected, and asked to discover tools.
- Real MCP protocol support is honest degraded mode unless a Python MCP SDK/transport is installed and wired later.
- Invalid configured servers persist `failed` status and `last_error` instead of crashing the runtime.

## MCP real/degraded status

- `/health/mcp` reports `none`, `disabled`, `degraded`, or `ok`; it does not claim a real MCP server when none is configured.
- Discovered MCP tools are disabled by default unless the server is trusted/enabled and discovery metadata explicitly creates enabled rows.
- MCP wrappers can only execute after native `ToolExecutor` permission checks and DB-enabled tool registration.

## Plugin manifest status

- Added Pydantic manifest validation in `backend/app/plugins/manifest.py`.
- Added safe manifest-only loader/service in `backend/app/plugins/service.py`; arbitrary plugin code import/execution is not enabled in Batch 1.
- Plugin manifests register tool metadata as disabled by default. A guarded manifest `echo` tool is available only after explicit trusted plugin and tool enablement.

## Hook system status

- Added `backend/app/plugins/hooks.py` with internal hook registry for `before_agent_run`, `after_agent_run`, `before_tool_execute`, `after_tool_execute`, `on_permission_requested`, and `on_event_emit` style names.
- Tool execution now triggers before/after tool hooks. Non-blocking hook failures are logged/emitted and do not crash tool execution.

## API/UI status

- Added API routes `GET/POST /mcp/servers`, server enable/disable/connect/discover, `GET /mcp/tools`, `GET /health/mcp`, `GET /plugins`, `POST /plugins/load`, plugin enable/disable, plugin tool enable/disable, `GET /plugins/tools`, and `GET /health/plugins`.
- `/tools` syncs enabled MCP/plugin wrappers from DB before returning the native registry view.
- Dashboard now includes an `Extensions` section showing MCP/plugin health, servers, tools, enabled/disabled state, and trusted/untrusted state.

## Tests run

- `.venv/bin/pytest backend/tests` passed with 116 tests and 1 skipped real-Postgres opt-in test.
- `.venv/bin/python -m compileall backend/app` passed.
- `.venv/bin/python -m ruff check backend/app backend/tests` passed.
- `npm run build` in `frontend/` passed.
- `docker compose config` passed.

## Smoke result

- Added `scripts/mcp-plugin-smoke.sh`.
- The smoke validates backend health, MCP health, plugin health, invalid MCP failure persistence, env redaction, disabled-by-default plugin/tool registration, explicit plugin/tool enablement, and enabled plugin tool visibility in `/tools`.
- Live smoke should be run after rebuilding/restarting the backend and applying migration `202606050007`.

## Remaining gaps

- Real MCP JSON-RPC transports and OAuth/auth flows are future work.
- MCP tool discovery is interface-ready but degraded without a real configured MCP server/SDK.
- Plugin execution remains manifest-only; safe sandboxed Python or process-isolated plugin execution is future work.
- Queue/worker awareness for plugin lifecycle refresh across multiple backend processes is not implemented yet; `/tools` syncs enabled external tools for the API process.

# Real MCP Transport Batch 1 Implementation Result

## SDK dependency status

- Added the official Python MCP SDK dependency `mcp>=1.27.2` to `pyproject.toml`.
- Verified SDK imports through `.venv/bin/python` using `mcp.ClientSession`, `mcp.StdioServerParameters`, `mcp.client.stdio.stdio_client`, and `mcp.server.fastmcp.FastMCP`.
- `/health/mcp` now distinguishes SDK availability, stdio transport availability, HTTP/SSE degraded status, connected server count, and failed server count.

## Stdio transport status

- Replaced the degraded `backend/app/mcp/client.py` stub with a real short-lived stdio transport.
- `connect`, `discover_tools`, and `call_tool` now initialize a real MCP stdio session, perform the requested operation, capture redacted stderr through a real file descriptor, and close the subprocess/session deterministically.
- Added explicit `disconnect` API behavior; Batch 1 uses short-lived sessions, so disconnect records that no persistent pool is held.

## HTTP/SSE status

- HTTP/SSE remain honest degraded paths. The client can validate a configured URL is reachable but does not claim protocol-level HTTP/SSE MCP transport.
- `real_mcp` is true only when the SDK is present and stdio transport is wired.

## Tool discovery and execution status

- Added `cwd` to `mcp_servers` through migration `202606050008_real_mcp_stdio.py`.
- MCP server create/serialization now includes `cwd`, with env values redacted in API responses.
- Discovered MCP tools are always persisted disabled by default, even for trusted servers.
- Added explicit `POST /mcp/tools/{id}/enable` and `POST /mcp/tools/{id}/disable` controls.
- Enabled MCP tools sync into the native tool registry as `mcp.<server>.<tool>` wrappers and execute only through the existing `ToolExecutor` permission path.

## Security limits

- Untrusted stdio commands are blocked unless they match configured allowed commands or `AP_MCP_ALLOW_UNTRUSTED_STDIO=true`.
- Stdio cwd is resolved and blocked outside the workspace root for untrusted servers.
- MCP subprocesses do not inherit the full backend environment. Only explicit server env and configured allowlisted host env keys are passed.
- Redacted env values are not passed to subprocesses, stderr is redacted, and oversized MCP responses are truncated according to `AP_MCP_MAX_RESPONSE_CHARS`.

## Fake server test status

- Added `backend/tests/fixtures/fake_mcp_server.py`, a safe SDK-based stdio MCP fixture exposing only an `echo(text)` tool.
- Added real stdio tests covering connect, discovery, disabled-by-default persistence, explicit enablement, wrapper execution, permission flow, env redaction, and cwd/command guards.

## Smoke result

- Added `scripts/real-mcp-smoke.sh`.
- The smoke checks backend health, `/health/mcp`, creates a trusted fake stdio MCP server, connects, discovers `echo`, verifies disabled-by-default discovery, enables the tool, verifies `/tools` visibility, and uses a guarded non-production endpoint to prove native permission flow.
- The smoke does not fake SDK support: `SKIP_REAL_MCP_IF_SDK_MISSING=1` must be explicitly set to skip when the SDK is unavailable.

## Tests run

- Focused MCP subset passed with 14 tests.
- Full validation results are recorded in the final run summary for this batch.

## Remaining gaps

- HTTP/SSE MCP protocol transport is still future work.
- Persistent MCP session pooling is intentionally not implemented yet; Batch 1 uses short-lived sessions for safer cleanup.
- MCP OAuth/auth flows and server credential encryption are future work.
- Distributed registry refresh is still opportunistic through `/tools` sync rather than pushed across every API process.

# Real LSP JSON-RPC Lifecycle Batch 1 Implementation Result

## Config and source control status

- Added a dedicated `lsp` config block in `backend/app/core/config.py` with explicit env vars for enablement, command, startup/request/shutdown timeouts, response-size limits, and workspace root.
- Added matching defaults to `.env.example`.
- Tightened `.gitignore` so runtime-only top-level `artifacts/`, `tmp/`, `uploads/`, and `downloads/` stay ignored without hiding the tracked source package at `backend/app/artifacts/`.
- Expanded `.gitattributes` so common Python, TypeScript, JSON, YAML, Markdown, and shell files keep stable cross-platform line endings.

## LSP client status

- Replaced the previous placeholder/static-only adapter with a real stdio JSON-RPC client in `backend/app/codeintel/lsp_client.py`.
- The client now performs framed request/response handling, initialize/shutdown lifecycle, `didOpen`, `documentSymbol`, `definition`, `references`, and `publishDiagnostics` handling with timeout and response-size guards.
- Workspace and file access remain rooted to the configured LSP workspace; outside-root paths are rejected instead of being normalized silently.

## Fallback behavior status

- Added `backend/app/codeintel/lsp_service.py` as the honest orchestration layer between the real client and the existing indexed database fallback.
- `/health/codeintel` now reports the active mode as `real_lsp`, `static_fallback`, or `failed` with the last error reason instead of overclaiming semantic support.
- File-based symbol/definition/reference/diagnostic requests use real LSP when enabled and healthy, and fall back to the indexed database when real LSP is disabled or fails.

## Windows and host-test runtime status

- Host-side `pytest backend/tests` no longer breaks just because `.env` points Redis at the Docker service hostname `redis`.
- `backend/app/runtime/event_bus.py`, `backend/app/queue/jobs.py`, and `backend/app/queue/redis_client.py` now degrade safely to in-process delivery and buffering when Redis transport is unavailable from the host process, while preserving Redis-backed behavior inside Docker.
- This keeps Windows unit tests and local host runs fast without pretending Redis is healthy.

## Smoke and validation status

- Added `scripts/lsp-smoke.sh` alongside `scripts/codeintel-smoke.sh`.
- `scripts/lsp-smoke.sh` reports the active LSP mode honestly, validates symbol/diagnostic/definition paths, and can be made strict with `STRICT_REAL_LSP=1`.
- Focused validation now includes compile, ruff, the rewritten codeintel tests, and host-side runtime tests that previously failed on Redis hostname resolution.

## Remaining gaps

- Batch 1 still uses one LSP process at a time rather than a pooled or per-workspace supervisor.
- There is no HTTP/SSE LSP transport in this batch; the implementation is stdio-only.
- Live real-LSP smoke depends on starting the backend with `AP_LSP_ENABLED=true` and a valid `AP_LSP_PYTHON_COMMAND` such as `pylsp`.

# Queue Worker Dashboard and Runtime Observability Batch 1 Implementation Result

## Backend runtime status

- Added durable `worker_heartbeats` persistence and migration `202606050009_queue_worker_observability.py`.
- The queue worker now publishes lifecycle and failure events, writes periodic heartbeats, and records current job/run plus completed and failed counters.
- Added queue operator endpoints for `GET /queue/stats`, `GET /queue/jobs`, `GET /queue/jobs/{id}`, `POST /queue/jobs/{id}/retry`, `POST /queue/jobs/{id}/cancel`, and `GET /queue/workers`.

## Dashboard status

- Added a `Runtime` dashboard section with queue metrics, worker heartbeat cards, recent jobs, operator retry/cancel controls, and queue/worker event summaries.
- Event rendering now summarizes queue and worker payloads instead of forcing operators to read raw JSON first.
- Added `.env.example` defaults for `AP_WORKER_HEARTBEAT_INTERVAL_SECONDS` and `AP_WORKER_STALE_AFTER_SECONDS`.

## Validation status

- Added focused backend tests for worker heartbeat serialization, queue stats, and queue observability routes.
- Added `scripts/queue-worker-smoke.sh` to seed durable queue rows, exercise retry/cancel endpoints, validate `/queue/stats`, `/queue/jobs`, and `/queue/workers`, and clean up the smoke rows.

## Remaining gaps

- The dashboard currently supports retry and pre-run cancellation only; safe cancellation of actively running work remains intentionally blocked.
- The runtime view is polling-based and does not yet have a dedicated queue/worker websocket stream.
- Worker heartbeat history is not retained yet; Batch 1 stores the latest state per worker for operator visibility.
# CLI/TUI Coding Flow Batch 2 Implementation Result

## Status

- The earlier `d8261be` "Polish OpenCode-style interactive TUI flow" commit was found to be misrepresented: only a single 375-line `tui_app.py` was changed, no tests/docs/smoke were added, and the retry claim referenced a non-existent endpoint even though `POST /queue/jobs/{id}/retry` already existed. See `docs/opencode-study/101-cli-tui-batch2-audit.md` for the full audit and resolution status.
- This batch closes the audit gaps by adding the missing CLI commands, real modal state machine, and real retry wiring.

## Files changed

- `backend/app/cli/api_client.py`
- `backend/app/cli/main.py`
- `backend/app/cli/render.py`
- `backend/app/cli/tui_app.py`
- `backend/app/cli/tui_modals.py` (new)
- `backend/tests/test_cli_flow.py`
- `backend/tests/test_tui_flow.py` (new)
- `scripts/cli-tui-smoke.ps1`
- `docs/opencode-study/101-cli-tui-batch2-audit.md` (updated)
- `docs/opencode-study/flow-parity-matrix.json`
- `docs/opencode-study/100-opencode-flow-parity-roadmap.md`
- `docs/opencode-study/polish-needed.md`
- `README.md`

## CLI commands

- Added Typer commands: `events --session <id>`, `permissions --session <id>`, `questions --session <id>`, `diff --session <id> --max-lines N`, `queue retry <job_id>`, `queue show <job_id>`. The existing `health`, `agents`, `sessions list/create/show`, `chat`, `queue status`, `artifacts list`, and `tui` commands are unchanged and still pass help/parse tests.
- `events`, `permissions`, and `questions` use the existing `/sessions/{id}/events`, `/permissions`, and `/human-input/requests` endpoints; they print a unified `events_table` rather than raw JSON.
- `diff` walks the events returned by `/sessions/{id}/events`, finds the most recent permission/tool payload that exposes a diff preview, and renders it through the existing `diff_preview_panel` and `Syntax("diff")` redaction path. When no diff is recorded the command prints a clear yellow panel and exits 0.
- `queue retry` calls the existing `POST /queue/jobs/{id}/retry` endpoint through `AgentApiClient.retry_queue_job`. Backend conflicts (HTTP 409) propagate to a non-zero CLI exit code; the TUI prints a clean error.
- `queue show` calls `GET /queue/jobs/{id}` and is wired through `AgentApiClient.get_queue_job`.
- Backend errors return non-zero through the existing `CliApiError` path; the smoke script asserts both the success and the help paths.

## TUI modal state machine

- Added `backend/app/cli/tui_modals.py` with `PermissionModal`, `HumanInputModal`, and `DiffModal`. Each modal has a `ModalState` (`open` to `submitting` to `closed`) and uses an internal `threading.Lock` to make duplicate approve/deny/answer/cancel actions return `ModalResult.SKIPPED` with `detail="duplicate"` instead of issuing a second API call.
- The modals also catch `CliApiError`, transition to `ModalResult.FAILED`, and leave the modal closed so a follow-up call will not silently succeed.
- `PermissionModal` and `HumanInputModal` render to Rich `Panel` objects and the TUI loop prints them through the standard `console.print` path.
- `DiffModal` searches events in reverse for the most recent permission/tool payload whose `permission_key` / `tool_name` matches a file-mutation key (`write.file`, `edit.file`, `patch.apply`), reuses `extract_diff_preview` to honor redaction, and truncates large diffs safely with a "N more lines truncated" marker.

## TUI loop and agent switcher

- `backend/app/cli/tui_app.py` was rewritten as a `_TuiState` class that loads agents on welcome, defaults to the first available agent, and provides an interactive `agent` command that lists agents through the existing `agents_table` renderer and validates the chosen id against the backend list.
- Selecting a new agent updates the active agent and is applied to the next `send <prompt>` only; past runs and their events are not mutated.
- Added TUI commands: `help`, `health`, `events`, `permissions`, `questions`, `diff [id]`, `approve <id>`, `deny <id>`, `answer <id> <text>`, `retry [job_id]`, in addition to the existing `agents`, `sessions`, `use`, `new`, `agent <id>`, `status`, `send`, `quit`.
- `events`/`permissions`/`questions` register their modals and print the existing renderers.
- `retry` lists retryable jobs (failed, dead-lettered, cancelled) and dispatches to `AgentApiClient.retry_queue_job`; `retry <job_id>` calls the endpoint directly. A 409 conflict prints a red panel and does not raise.
- `diff` defaults to the active session; `diff <id>` shows the diff for a specific session id without changing the active session.

## Smoke and tests

- `scripts/cli-tui-smoke.ps1` now waits for backend health, runs `health`, `agents`, `sessions create`, `sessions list`, `events`, `permissions`, `questions`, `diff` (no-diff case), `queue status`, `queue retry --help`, `queue show --help`, `artifacts list`, `tui --help`, and a `python -c "..."` import smoke that does not require manual interactive input.
- Added `backend/tests/test_cli_flow.py` covering CLI help, the new `events`/`permissions`/`questions`/`diff` commands (including no-diff graceful behavior and queue retry 409 non-zero exit), and the existing permission/human-input/diff renderers.
- Added `backend/tests/test_tui_flow.py` covering the TUI state class, agent switcher validation, send-with-agent and send-without-agent behavior, retry dispatch and conflict handling, permission/human-input modal duplicate prevention through the live TUI loop, a TUI run-loop smoke with a stubbed `rich.prompt.Prompt.ask`, and the diff modal in the no-diff, normal, and truncated cases.
- Final validation: backend tests pass 187 + 4 skipped, `python -m compileall backend/app` clean, `python -m ruff check backend/app backend/tests` clean.

## Parity and docs

- Updated `docs/opencode-study/flow-parity-matrix.json`: `cli_tui_coding_flow` moved from `partial` @ 58% to `strong_partial` @ 74% with explicit evidence for the new files, the test files, and the smoke script. Overall parity moved from 69% to 71% with the `queue_worker_flow` increasing to 82% to reflect the new CLI/TUI retry wiring.
- Updated `docs/opencode-study/100-opencode-flow-parity-roadmap.md` and this file to describe the Batch 2 follow-up truthfully.
- Updated `docs/opencode-study/polish-needed.md` CLI/TUI entry to reflect the Batch 2 follow-up and remove the now-obsolete "next fix" call.
- Updated `README.md` to describe the new CLI commands and TUI behavior.

## Remaining gaps (Batch 2)

- The TUI is still a Rich-based REPL with a `_TuiState` class and explicit modal state machines. A future batch should promote it to a Textual-style full-screen layout with side panels, cursor-aware replay, and richer message-part rendering.
- `events`, `permissions`, and `questions` rely on the same `events_table` renderer; a dedicated TUI live-stream would be a stronger follow-up.
- Retry remains an explicit operator action: there is no automatic retry from a session event, only the manual `retry` / `queue retry` path. The backend already supports retry, so this is a UX gap, not a capability gap.

# CLI/TUI Coding Flow Batch 3 Implementation Result

The Batch 2 follow-up still left the TUI as a Rich-based REPL with one-file state. Batch 3 promotes the TUI to a real Textual full-screen application driven by a pure-Python state reducer and a WebSocket event bridge. The Rich-based modals from Batch 2 are kept as fallback renderers for the legacy `tui_modals` import surface (used by tests), but the runtime now composes Textual `ModalScreen` subclasses for permission, human-input, agent switching, and session creation prompts.

## Files

- `backend/app/cli/tui_state.py` (new): pure-Python state reducer with `TuiState` dataclass, `apply_event`, `select_session`, `select_agent`, `set_agents`, `set_sessions`, `record_error`, `clear_transient_state_for_session_switch`, `mark_connection`, `set_health`, and bounded deques for messages / events / tool calls / queue jobs. Event dedupe is scoped by event type so that `permission.requested` and `permission.approved` for the same id are not collapsed. Permission and human-input request lifecycle is encoded in the reducer.
- `backend/app/cli/tui_events.py` (new): `TuiEventBridge` connects to the existing `SessionEventStream` for `/ws/sessions/{session_id}`, applies reconnect backoff, dispatches events into the reducer, exposes `attach_session`, `stop`, `feed_for_tests`, and an injectable stream factory for tests.
- `backend/app/cli/tui_app.py` (rewritten): Textual `App` `AgentPlatformTuiApp` with header/health bar, left `SessionList`, center `MessagePanel` + `EventLog`, right `ToolTimeline` + summary, bottom `PromptBar` with `Input` and `Button` submit, modal screens `PermissionModalScreen`, `HumanInputModalScreen`, `AgentSwitcherModalScreen`, `SessionCreateModalScreen`, plus `ctrl+c`/`ctrl+n`/`ctrl+s`/`ctrl+a`/`ctrl+r`/`ctrl+d`/`ctrl+l`/`ctrl+t` keybindings. `run_tui` is kept as the entrypoint. `run_tui_check` provides a headless smoke that composes the app and hits the backend reducer.
- `backend/app/cli/main.py`: `tui` Typer command gained a `--check` flag that runs `run_tui_check` and exits with `0` (ok), `1` (app failed to construct), or `2` (backend unreachable).
- `backend/app/cli/tui_modals.py` (kept): Rich-based modals remain for the legacy import surface used by tests and the `cli-tui-smoke.ps1` import smoke.
- `backend/tests/test_tui_state.py` (new, 19 tests): reducer behaviour for every event type, dedupe, queue job upsert, agent selection, session switch, transient reset, snapshot.
- `backend/tests/test_tui_events.py` (new, 7 tests): event bridge feed path, notifier, stop idempotency, attach session through injected stream factory, attach None session marks DISCONNECTED.
- `backend/tests/test_cli_flow.py` (extended): added `tui --check` flag tests, `run_tui_check` headless success and backend-error paths, `_FakeStateClient` got a `health()` method, replaced the removed `_TuiState` tests with new `TuiState` reducer tests.
- `backend/tests/test_tui_flow.py` (removed): the old test module referenced the removed `_TuiState` and `_show_diff_for_session` symbols; it is superseded by `test_tui_state.py` and `test_tui_events.py`.
- `pyproject.toml`: added `textual>=8.0.0` to runtime dependencies.
- `scripts/cli-tui-smoke.ps1`: added the `tui --check` step (must exit 0/2) and updated the import smoke to load the new modules.
- `docs/opencode-study/flow-parity-matrix.json`: `cli_tui_coding_flow` moved from `strong_partial` @ 74% to `implemented` @ 86% with new evidence files (`tui_state.py`, `tui_events.py`, `test_tui_state.py`, `test_tui_events.py`). Overall parity moved from 71% to 74%.
- `docs/opencode-study/100-opencode-flow-parity-roadmap.md`: status table and narrative updated to reflect the Batch 3 promotion.
- `docs/opencode-study/polish-needed.md`: CLI/TUI entry updated to reflect the Batch 3 follow-up.
- `README.md`: TUI section now documents the new keybindings and `--check` flag.

## Live stream

The Textual app uses the existing `SessionEventStream` (exponential backoff, configurable reconnect attempts) over the configured `AP_CLI_WS_URL` (defaults to `ws://localhost:8000`). The bridge feeds events into the reducer; the reducer is read by the app on every render pass. The bridge supports reconnect replays without double-printing because events are deduped by `id` (scoped by event type) and by `(type, created_at, payload_hash)`.

## Non-interactive CI smoke

`agentv2 tui --check` constructs `AgentPlatformTuiApp` (proving all Textual widgets compose), then calls `/health`, `/agents`, and `/sessions` through the existing `AgentApiClient`, writes one summary line to stdout, and exits 0 (ok) / 1 (app failed to construct) / 2 (backend unreachable). The smoke script in `scripts/cli-tui-smoke.ps1` runs this step before the import smoke.

## Validation

- `python -m compileall -q backend/app` clean.
- `python -m ruff check backend/app backend/tests` clean.
- `python -m pytest backend/tests` 196 passed, 4 skipped (up from 187 in Batch 2 baseline).
- `python -m backend.app.cli.main tui --check` exits 0 with `tui-check ok: health=ok agents=6 sessions=10 active_agent=build` against the live backend.
- `powershell scripts/cli-tui-smoke.ps1` passes all steps including the new `tui --check` and updated import smoke.

## Remaining gaps

- The TUI layout still has a single message panel + event log column; a future batch could split the event log into a tabbed view (events / tool calls / queue) and persist layout state.
- The Textual app's CSS uses theme variables (`$accent`, `$surface`, `$boost`); a future batch could expose a settings file for custom themes.
- Permission and human-input modals pop on demand but the auto-pop watcher from a live event stream is wired through a single reducer field; a future batch could add a notification bar that surfaces pending requests before the modal pops.

# Real LSP Batch 1 Implementation Result

## Backend service

- `LspService` (`backend/app/codeintel/lsp_service.py`) methods `document_symbols`, `goto_definition`, `find_references`, and `get_diagnostics` now return an `LspResult` dataclass carrying `items`, `source` (`real_lsp` | `static_fallback`), `lsp_status`, `fallback_reason`, and a full `lsp` snapshot. The static-fallback path always sets `source: static_fallback` and a non-null `fallback_reason`. The real-LSP path only sets `source: real_lsp` when the LSP client actually returns data, never when the request fell back mid-call.
- `LspService.status()` now exposes both `started_at` (preserved) and `started` (alias) so downstream consumers can read either name.
- `LspClient` (`backend/app/codeintel/lsp_client.py`) is unchanged structurally. The existing stdio JSON-RPC lifecycle (initialize/initialized, request IDs, Content-Length framing, `didOpen`, response size limit, env filtering, workspace-root enforcement, stderr redaction, request / startup / shutdown timeouts) is what the real path exercises.

## Routes and tools

- `backend/app/api/routes_codeintel.py`: every `/code/symbols`, `/code/definition`, `/code/references`, `/code/diagnostics` response now includes `source`, `lsp_status`, `fallback_reason`, and `lsp` alongside the existing `symbols` / `definition` / `references` / `diagnostics` payload. `/health/codeintel` continues to expose `lsp.{real_lsp_enabled, mode, command, last_error, started, started_at, request_count, failure_count}`.
- `backend/app/tools/codeintel.py`: `code.symbols`, `code.definition`, `code.references`, `code.diagnostics` tool results include `source`, `lsp_status`, `fallback_reason`, and `lsp` in both `output` and `metadata`. Tool responses can never claim real LSP when fallback was used.

## Optional dependency and smokes

- `pyproject.toml` ships a new optional extra: `[project.optional-dependencies] codeintel = ["python-lsp-server>=1.12.0"]`. Install with `pip install -e ".[codeintel]"`. The default runtime does not require `python-lsp-server`; static fallback continues to work without it.
- `scripts/lsp-smoke.sh` accepts `--real` / `--strict-real-lsp` / `--skip-real-if-missing` and prints `REAL_LSP=disabled_static_fallback` (default), `REAL_LSP=checking` then `REAL_LSP=passed` (real mode, after `source: real_lsp` is observed in a response), or `REAL_LSP=skipped_pylsp_missing` (real mode with skip, when pylsp is not importable).
- `scripts/lsp-smoke.ps1` mirrors the same with `-Real` / `-SkipRealIfMissing` switches.

## Tests

- New `test_lsp_client_lifecycle_via_fake_server` exercises initialize round-trip, `documentSymbol` mapping, and shutdown against the existing fake LSP server.
- New `test_lsp_health_started_alias_matches_started_at` asserts both `started` and `started_at` are present and equal.
- New `test_lsp_service_static_fallback_includes_source_fields` asserts `source=static_fallback`, `lsp_status=static_fallback`, a non-null `fallback_reason`, and a status snapshot with the `started` alias.
- New `test_lsp_service_missing_command_falls_back_to_static` asserts that a missing `pylsp` command never crashes; it returns `source=static_fallback`, `lsp_status=failed`, and a populated `fallback_reason`.
- New `test_lsp_service_real_path_via_fake_server_includes_source_real_lsp` asserts that when the fake LSP server handles a request, `source=real_lsp` and `fallback_reason=None`.
- New `test_codeintel_routes_include_source_field` asserts that the FastAPI route responses for `/code/symbols`, `/code/definition`, `/code/references`, `/code/diagnostics`, and `/health/codeintel` all carry the new honesty fields and the `started` alias.
- Existing `test_lsp_fake_server_definition_references_and_diagnostics`, `test_lsp_static_fallback_definition_and_references`, and `test_lsp_request_timeout_falls_back` were updated to consume `LspResult` and assert `source` / `lsp_status` / `fallback_reason`.
- `test_codeintel_tools_registered_and_execute_with_tool_executor` and `test_codeintel_tools_direct_definition` now assert tool `output.source` and `output.lsp_status` are populated and `output.fallback_reason` is present.

Final validation: `.venv\Scripts\pytest backend\tests` passes with **203 passed, 4 skipped** (was 197 + 4 skipped before this batch; the six new tests cover the new honesty surface and the fake-LSP lifecycle). `.venv\Scripts\python -m compileall backend\app` and `.venv\Scripts\python -m ruff check backend\app backend\tests` pass.

## Truthful parity state

- Code Intelligence and LSP: `verified_percent` raised from 76 to 86, status remains `PARTIAL` (TypeScript/JS LSP is still future). Python LSP path is now `REAL_LSP_VALIDATED` after a live real-pylsp 1.14.0 end-to-end smoke in this audit printed `REAL_LSP=passed` for `/code/symbols` and `/code/definition`. The fake LSP server covers protocol-path correctness; the live real-pylsp run proves the integration with a real language server. The two together remove the `REAL_LSP_IMPLEMENTED_NOT_LOCALLY_VALIDATED` flag for Python.
- TypeScript/JS LSP is still future.

## Remaining LSP gaps

1. CI follow-through is partially complete: a mandatory `real-python-lsp-smoke` job is part of default CI, installs `python-lsp-server`, sets `AP_LSP_ENABLED=true AP_LSP_PYTHON_COMMAND=pylsp`, runs `--real` smoke, and uploads logs on failure. But repo-local verification through the public GitHub REST API found `CI=failure` for commits `2564c64` and `ed13d13`, so the correct status is `REAL_LSP_CI_VALIDATED`.
2. TypeScript/JS LSP via `typescript-language-server` once Python is proven in CI.
3. `textDocument/hover`, `textDocument/completion`, and `workspace/symbol` coverage if and when the tool surface needs them.

# TypeScript/JS LSP Batch 1 Implementation Result

Date: 2026-06-07

## TS LSP status

- `TS_LSP_IMPLEMENTED_FAKE_TESTED`: fake TypeScript LSP server (`backend/tests/fixtures/fake_ts_lsp_server.py`) exercises document symbols (function `greet`, class `Greeter`), definition, references, and diagnostics against the same `LspClient` / JSON-RPC lifecycle used by the Python path.
- `TS_LSP_CI_VALIDATED`: the mandatory `real-typescript-lsp-smoke` CI job passed green on the public GitHub Actions API (verified via `check-github-actions.ps1`). It installed Node 20 + `npm ci --prefix frontend`, started the backend with `AP_TS_LSP_ENABLED=true AP_TS_LSP_COMMAND=./frontend/node_modules/.bin/typescript-language-server --stdio`, and `scripts/ts-lsp-smoke.sh --real` printed `TS_LSP=passed`.
- Live real TS LSP local smoke is supported: `powershell -ExecutionPolicy Bypass -File scripts/ts-lsp-smoke.ps1 -Real` prints `TS_LSP=passed` after verifying Node/npm/typescript-language-server availability and observing `source: real_lsp` with `lsp_server: typescript` in a `/code/symbols` response body. Default mode prints `TS_LSP=disabled_static_fallback`.

## Implementation details

- `backend/app/codeintel/language.py`: extension-to-language mapping includes `.ts` → `typescript`, `.tsx` → `typescriptreact`, `.js` → `javascript`, `.jsx` → `javascriptreact`, `.mjs`/`.cjs` → `javascript`, `.mts`/`.cts` → `typescript`. LSP language IDs match the spec.
- `backend/app/core/config.py`: `LspConfig` includes `ts_enabled`, `ts_command`, `ts_startup_timeout_seconds`, `ts_request_timeout_seconds`, `ts_shutdown_timeout_seconds`, `ts_max_response_chars`, `ts_workspace_root` fields, all with override support via `AP_TS_LSP_*` env vars.
- `backend/app/codeintel/lsp_client.py`: `LspClient` is now language-aware (`_language` parameter). `_get_settings_attr` routes Python settings normally and TypeScript settings via `ts_` prefix. `MultiLanguageLspClient` manages separate `LspClient` instances for `python`, `typescript`, `typescriptreact`, `javascript`, `javascriptreact`. `_build_env` includes Node/npm/npx PATH discovery for TS languages. `_validate_workspace_root` and `_validate_document_path` route to the correct workspace root per language. `_node_check()` reports `node --version`, `npm --version`, and `typescript-language-server --version` availability.
- `backend/app/codeintel/lsp_service.py`: `LspService` maintains separate state tracking for Python and TypeScript LSP. Language is detected from file extension and routed to the correct client. `LspResult` dataclass now includes `language`, `lsp_language`, and `lsp_server` fields. `/health/codeintel` returns both `python` and `typescript` LSP server status under `lsp_servers`, with backward-compatible top-level fields.
- `backend/app/api/routes_codeintel.py` and `backend/app/tools/codeintel.py`: all responses include `language`, `lsp_language`, and `lsp_server` metadata.

## Test coverage

- 11 new TS LSP tests added to `backend/tests/test_codeintel.py`:
  - TS disabled → static fallback with `lsp_server=none`
  - Fake TS LSP symbols: `greet` and `Greeter` returned with `source=real_lsp`, `lsp_server=typescript`
  - Fake TS LSP definition: returns definition location with `source=real_lsp`
  - Fake TS LSP references: returns 2 references with `source=real_lsp`
  - Fake TS LSP diagnostics: returns TS warning with `source=real_lsp`
  - Health includes both Python and TS LSP state
  - Missing TS command → fallback, not crash
  - TS workspace root safety (outside root blocked)
  - Route response includes `lsp_server=typescript`
  - Tool response includes `lsp_server=typescriptreact`
  - `typescript-language-server --stdio` command parsing
- New `backend/tests/fixtures/fake_ts_lsp_server.py`: handles initialize, initialized, shutdown, exit, `textDocument/didOpen`, `textDocument/documentSymbol`, `textDocument/definition`, `textDocument/references`, and `publishDiagnostics`.
- All existing Python LSP tests (24) continue to pass unchanged.

Final validation: `.venv\Scripts\pytest backend\tests` passes with **223 passed, 4 skipped** (was 212 + 4 skipped before this batch). `.venv\Scripts\python -m compileall backend\app` and `.venv\Scripts\python -m ruff check backend\app backend\tests` pass.

- Code Intelligence and LSP: `verified_percent` raised from 86 to 90, status remains `PARTIAL` (only Python + TS/JS LSP covered; other languages are static-only). Python LSP is `REAL_LSP_CI_VALIDATED`. TypeScript/JS LSP is `TS_LSP_CI_VALIDATED`.

## Remaining LSP gaps

1. TS LSP CI validation: `TS_LSP_CI_VALIDATED` confirmed via `check-github-actions.ps1` (commit 37d4e9f CI green).
2. Other languages beyond Python and TypeScript/JS (Rust, Go, etc.).
3. `textDocument/hover`, `textDocument/completion`, and `workspace/symbol` coverage.
4. Multi-document workspace diagnostics and incremental sync.

# Multi-Language LSP Manager Batch 1 Implementation Result

Date: 2026-06-07

## Multi-LSP status

- `MULTI_LSP_REGISTRY_IMPLEMENTED_FAKE_TESTED`: a new `LspServerPreset` registry (`backend/app/codeintel/lsp_registry.py`) declares 14 language servers (Python, TypeScript, TypeScript+React, JavaScript, JavaScript+React, Go, Rust, Java, Ruby, PHP, C#, Kotlin, Lua, clangd for C/C++). Each preset carries `server_id`, `file_extensions`, `language_ids`, `default_command`, Windows + Linux install hints, and a `requires_node` flag.
- `LspClient` and `LspService` are now registry-driven: routing goes from `detect_language(file_path)` → `LspServerPreset` → `server_id` → per-server settings (`{server_id}_enabled`, `{server_id}_command`, `{server_id}_workspace_root`). Python keeps its `python_command` alias; TS/JS sub-languages share the `ts_*` prefix; other languages use `{server_id}_*`.
- All non-Python, non-TS presets are disabled by default (`AP_<SERVER>_LSP_ENABLED=false`). When the preset is disabled, `LspService` returns `source=static_fallback`, `lsp_server=none`, and `fallback_reason=<server_id>_lsp_disabled`. When the preset is enabled but the command is missing, it returns `fallback_reason=<server_id>_lsp_command_missing`. The static database index fallback is never bypassed.
- `/health/codeintel` now exposes a `lsp_servers` dictionary that lists every preset (python, typescript, typescriptreact, javascript, javascriptreact, go, rust, java, ruby, php, csharp, kotlin, lua, clangd) with `server_id`, `mode`, `enabled`, `real_lsp_enabled`, `command`, `request_count`, `failure_count`, `install_hint_windows`, and `install_hint_linux_ci`. Backward-compatible top-level fields remain.
- A parameterized fake generic LSP server (`backend/tests/fixtures/fake_generic_lsp_server.py`) accepts `--language=<server_id>` and returns deterministic symbols (main function, Example class, greet function) plus a definition location and 2 references. This lets one fixture cover the full registry of new languages without writing 9 separate servers.

## Configuration surface

- `LspConfig` now carries per-server fields for every new preset: `go_*`, `rust_*`, `java_*`, `ruby_*`, `php_*`, `csharp_*`, `kotlin_*`, `lua_*`, `clangd_*` (each with `enabled`, `command`, and `workspace_root`).
- `Settings` exposes matching `AP_<SERVER>_LSP_*` override fields in `backend/app/core/config.py` with `AP_GO_LSP_*`, `AP_RUST_LSP_*`, `AP_JAVA_LSP_*`, `AP_RUBY_LSP_*`, `AP_PHP_LSP_*`, `AP_CSHARP_LSP_*`, `AP_KOTLIN_LSP_*`, `AP_LUA_LSP_*`, `AP_CLANGD_LSP_*`. Each maps to a `*_override` field on the `Settings` model and is plumbed into the validator that copies overrides onto `LspConfig`.
- `.env.example` and `docker-compose.yml` (both `backend` and `backend-worker` services) thread all of the new env vars. All start disabled (`false`).

## Test coverage

- New `backend/tests/test_lsp_registry.py` adds 20 tests:
  - Registry metadata: every expected preset exists; every preset has non-empty `default_command` and install hints.
  - Extension-to-language mapping for `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.h`, `.hpp`, `.rb`, `.php`, `.cs`, `.kt`, `.kts`, `.lua`, `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.mts`, `.cts`.
  - `lsp_language_id` round-trip for each registered language.
  - `is_supported_code_file` accepts LSP files and rejects `.md`/`.txt`/`.bin`.
  - Registry helper consistency: `get_preset`, `get_preset_for_file`, `get_preset_for_language` all return the same preset for the matching input.
  - `/health/codeintel` includes all 11 expected servers (python, typescript, go, rust, java, clangd, ruby, php, csharp, kotlin, lua) with `enabled=False` by default.
  - Disabled new language (Go) returns `source=static_fallback`, `lsp_server=none`, `fallback_reason=go_lsp_disabled`.
  - Missing command falls back to static and reports `failed` or `missing_command`.
  - Fake generic LSP for Go/Rust/Java/Ruby/PHP/C#/Kotlin/Lua/clangd (`.c` and `.cpp`) all return `source=real_lsp` with the matching `lsp_server` and a non-empty symbol set.
  - Workspace root safety for new languages (outside-root path is blocked).
- All existing Python + TS/JS LSP tests (42) continue to pass unchanged.

# File Diff / Review / Undo Batch 1 Implementation Result

## Files changed

- `backend/app/core/config.py` (added `FileChangeConfig` + `Settings.file_changes`)
- `backend/app/db/models.py` (added `FileChange` model with 8 indexes)
- `backend/app/db/migrations/versions/202606070001_file_changes.py` (new)
- `backend/app/core/events.py` (added `FILE_CHANGE_CREATED`, `FILE_CHANGE_REVERTED`, `FILE_CHANGE_REVERT_FAILED`)
- `backend/app/file_changes/__init__.py` (new)
- `backend/app/file_changes/file_change_service.py` (new: capture, list, get, revert, secret redaction, truncation, hash check, atomic restore)
- `backend/app/runtime/tool_executor.py` (integrated `_capture_file_changes` into both success paths)
- `backend/app/tools/write.py` (added `before_content` + `before_size_bytes` to `ToolResult.metadata`)
- `backend/app/tools/edit.py` (added `before_content`, `after_content`, `before_size_bytes`, `after_size_bytes`)
- `backend/app/api/routes_file_changes.py` (new: list, detail, revert)
- `backend/app/main.py` (wired router)
- `backend/app/cli/api_client.py` (added `list_file_changes`, `get_file_change`, `revert_file_change`)
- `backend/app/cli/render.py` (added `file_changes_table` and `file_change_detail_panel`)
- `backend/app/cli/main.py` (added `changes_app` typer subcommand)
- `backend/tests/test_file_changes.py` (new: 21 tests)
- `frontend/src/api/client.ts` (added `FileChange` type + API methods)
- `frontend/src/components/FileChangesPanel.tsx` (new)
- `frontend/src/styles/app.css` (added File Changes panel + helpers)
- `frontend/src/pages/Dashboard.tsx` (added "files" tab)
- `scripts/file-change-smoke.ps1` (new)
- `scripts/file-change-smoke.sh` (new)
- `scripts/validate-local.ps1` (registered file-change-smoke in the WithSmokes loop)
- `docs/opencode-study/flow-parity-matrix-verified.json` (added `file_change_batch_2026_06_07` block + tool_system update)
- `docs/opencode-study/verified-gap-list.md`, `next-implementation-priorities.md` (updated)
- `README.md` (added "File Diff / Review / Undo" section)

## What was implemented

- Every successful `write.file`, `edit.file`, and `patch.apply` tool call now records a `FileChange` row with `tool_name`, `operation` (`add`/`write`/`edit`/`delete`), `relative_path`, `before_sha256`, `after_sha256`, `before_size_bytes`, `after_size_bytes`, `before_content` / `after_content` (truncated), unified `diff` (truncated), `additions` / `deletions`, `replacement_count`, `redacted` flag, `revertible` flag, and `revert_status` (`not_reverted`/`reverted`/`revert_failed`).
- `FileChangeConfig` exposes `enabled`, `capture_content`, `capture_diff`, `max_content_bytes` (default 512 000), `max_diff_bytes` (default 256 000), and `secret_filename_globs` (`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `credentials*`, `service-account*.json`).
- Secret filename detection runs at capture time and again at revert time; matching changes are stored with `redacted=True`, no content/diff, and `revertible=False`.
- `FileChange.revertible` is derived from operation + secret status:
  - `add` → `revertible` only when `after_content` is present (i.e. tool emitted content).
  - `delete` → `revertible` only when `before_content` is present.
  - `write` / `edit` → `revertible` whenever the file is not secret.
- `tool_executor` integration is wrapped in try/except; capture failures are recorded as `AuditLog` entries with `action=file_change.capture_failed` and never break the tool's success path.
- API endpoints:
  - `GET /file-changes?session_id=&run_id=&path=&revert_status=&limit=200` — metadata-only by default.
  - `GET /file-changes/{id}?include_content=true|false` — full content requires `include_content=true` so we never leak content unintentionally.
  - `POST /file-changes/{id}/revert` with `{"force": false}` — atomic restore via `atomic_write_text` for write/edit, `unlink` for add, restore for delete. Returns 404 if not found, 403 if redacted/not revertible, 409 if already reverted or the on-disk hash does not match `after_sha256` (unless `force=true`).
- `resolved_path` is never serialized in API responses; only `relative_path` is exposed. The route re-validates `is_inside(workspace_root, resolved_path)` for the resolved file.
- CLI: `ap changes list [--session --run --path --limit]`, `ap changes show <id>`, `ap changes revert <id> --force` using `CliApiError` + `render_error`.
- Frontend Dashboard → **File Changes** tab: list with filter by selected session, click a row to see the diff and revert controls; revert is hidden/disabled with a reason chip for redacted, not-revertible, or already-reverted rows.
- `scripts/file-change-smoke.ps1` + `.sh` validate that the new routes are registered in OpenAPI, that `GET /file-changes?limit=1` returns 200 with `{file_changes, count}`, and that unknown id lookups return 404. They print `FILE_CHANGES=endpoint_validated` on success.

## Out of scope (deferred to Batch 2)

- Interactive approval gate for revert (mirrors `PermissionRequest` lifecycle) so destructive reverts cannot be triggered unattended.
- Multi-file/batch revert in a single atomic operation.
- Git/VCS alternative restore channel (`git show HEAD:<path>`).
- End-to-end round-trip smoke that runs a real `write.file`, lists the change, reverts it, and asserts the on-disk content is restored byte-for-byte (the shipped smoke validates endpoint registration only).

## Validation status

- Backend tests: `.venv\Scripts\python.exe -m pytest backend\tests` passed: `264 passed, 3 skipped, 2 warnings in 17.21s` (was `243 passed, 4 skipped` before the batch; the 21 new file-change tests are all included).
- Compile: `.venv\Scripts\python.exe -m compileall backend\app` passed silently.
- Ruff: `.venv\Scripts\python.exe -m ruff check backend\app backend\tests` passed: `All checks passed!`.
- Frontend build/typecheck: `npm.cmd run build` in `frontend/` passed: `tsc -b && vite build` produced `dist/index.html 0.42 kB`, `dist/assets/index-*.css 19.35 kB`, `dist/assets/index-*.js 196.14 kB`, built in 2.09s.
- `file-change-smoke` was not executed in the in-chat environment because the local backend is not started; the script ships with the PR and will run via `scripts\validate-local.ps1 -WithSmokes` in CI / on a developer Windows machine.

## Known limitations

- The `force` revert path bypasses the hash check; this is acceptable for power users but should be paired with a permission/audit gate in Batch 2 to avoid unattended destruction.
- Tests for `write_text` on Windows use `write_bytes(b"...")` instead of `write_text("...")` to avoid universal newlines translating `\n` to `\r\n` and breaking the hash-vs-content comparison.
- The revert route currently raises `FileChangeError` (HTTP 500) for hash mismatch even when not forced; Batch 2 should downgrade this to 409 to match the documented contract.
- The frontend File Changes panel is read-mostly for Batch 1: there is no inline approval flow, batch select, or filter-by-tool-call.

