# Polish Needed

## Backend

### Project/workspace structure
- Current problem: Bootstrap tenant still behaves like a default local user; Frontend does not expose organization/project/workspace selection
- Why it matters: Runs can target the wrong workspace root once multiple workspaces exist.
- Exact file(s): `backend/app/api/routes_workspaces.py`
- Exact recommended fix: Add project/workspace list/select routes and require selected workspace context on session creation.
- Risk if ignored: Runs can target the wrong workspace root once multiple workspaces exist.

### Configuration system
- Current problem: Development defaults include credentials and broad local assumptions; Settings are cached until restart
- Why it matters: Permission and model behavior cannot be safely tuned per project without auditable scoped config.
- Exact file(s): `backend/app/core/config.py`
- Exact recommended fix: Add environment mode validation and a database-backed settings overlay for permission/model defaults.
- Risk if ignored: Permission and model behavior cannot be safely tuned per project without auditable scoped config.

### Server boot lifecycle
- Current problem: Lifespan configures logging only; CLI migrate shells out without structured errors
- Why it matters: Containers can report healthy while runtime dependencies are degraded.
- Exact file(s): `backend/app/main.py`
- Exact recommended fix: Add startup checks for migrations/dependencies and shutdown hooks for background tasks.
- Risk if ignored: Containers can report healthy while runtime dependencies are degraded.

### API route structure
- Current problem: Plain dict responses lack shared envelopes; Some detail endpoints do not tenant-filter before returning rows
- Why it matters: Frontend and future SDK contracts can drift as routes grow.
- Exact file(s): `backend/app/api/__init__.py`
- Exact recommended fix: Introduce versioned routers and shared response/error schemas while preserving current aliases.
- Risk if ignored: Frontend and future SDK contracts can drift as routes grow.

### OpenAPI/schema generation
- Current problem: Manual frontend types can silently drift; OpenAPI descriptions are sparse
- Why it matters: A backend change can break the UI without compile-time feedback.
- Exact file(s): `frontend/src/api/client.ts`
- Exact recommended fix: Add OpenAPI generation and replace manual wire types with generated or schema-checked types.
- Risk if ignored: A backend change can break the UI without compile-time feedback.

### Session model
- Current problem: Session detail does not tenant-check the requested session; Status values are unconstrained strings
- Why it matters: Session lineage, accounting, and tenant safety are incomplete.
- Exact file(s): `backend/app/db/models.py`
- Exact recommended fix: Add session lineage/lifecycle fields, enum constraints, and tenant-scoped detail loading.
- Risk if ignored: Session lineage, accounting, and tenant safety are incomplete.

### Message model
- Current problem: parts is unvalidated JSONB; Tool calls are separate and not rich message parts
- Why it matters: The UI cannot render precise execution timelines or artifacts without ad hoc metadata parsing.
- Exact file(s): `backend/app/runtime/message_service.py`
- Exact recommended fix: Introduce Pydantic message-part schemas for assistant, tool, permission, and artifact parts.
- Risk if ignored: The UI cannot render precise execution timelines or artifacts without ad hoc metadata parsing.

### Event system
- Current problem: In-process subscribers do not work across replicas; Payloads are untyped JSON
- Why it matters: Multi-container deployments will lose live events for sessions handled by another process.
- Exact file(s): `backend/app/runtime/event_bus.py`
- Exact recommended fix: Add typed event schemas and Redis-backed pub/sub while keeping SystemEvent as durable store.
- Risk if ignored: Multi-container deployments will lose live events for sessions handled by another process.

### WebSocket/realtime events
- Current problem: Receive loop ignores client messages; UI refetches full session detail on every event
- Why it matters: Users can miss permission prompts or tool updates during network blips.
- Exact file(s): `frontend/src/stores/eventStore.ts`
- Exact recommended fix: Create typed event store with reconnect/replay and backend cursor replay support.
- Risk if ignored: Users can miss permission prompts or tool updates during network blips.

### Agent registry
- Current problem: Prompts are terse and JSON-protocol focused; Allowed tools are fixed at startup
- Why it matters: Operators cannot tune agents without code changes.
- Exact file(s): `backend/app/agents/registry.py`
- Exact recommended fix: Load validated agent overrides from database while retaining safe built-in defaults.
- Risk if ignored: Operators cannot tune agents without code changes.

### Native agents
- Current problem: Prompts are embedded constants; general chat still has editing tools
- Why it matters: Local chat can request high-authority tools unless permissions catch every path.
- Exact file(s): `backend/app/agents/prompts.py`
- Exact recommended fix: Move prompts into versioned modules/files and reduce general chat tool authority by default.
- Risk if ignored: Local chat can request high-authority tools unless permissions catch every path.

### Agent prompts/system instructions
- Current problem: Local models often ignore strict JSON; Tool schema lacks examples
- Why it matters: The platform may chat but fail to reliably invoke tools for implementation tasks.
- Exact file(s): `backend/app/runtime/context_builder.py`
- Exact recommended fix: Build a prompt/context composer with role prompt, guardrails, tool examples, workspace summary, and compacted history.
- Risk if ignored: The platform may chat but fail to reliably invoke tools for implementation tasks.

### Doom-loop/repeated action protection
- Current problem: Only exact JSON matches are blocked; Loop guard exception may skip audit log
- Why it matters: Repeated harmful variants can still consume resources or mutate state.
- Exact file(s): `backend/app/runtime/loop_guard.py`
- Exact recommended fix: Persist loop-guard denials and normalize shell/file inputs before hashing.
- Risk if ignored: Repeated harmful variants can still consume resources or mutate state.

### Audit logging
- Current problem: Audit metadata is unredacted JSON; resource_id is not FK-linked
- Why it matters: Security investigations will miss who prompted, which model was called, and what data was exposed.
- Exact file(s): `backend/app/audit/service.py`
- Exact recommended fix: Centralize audit logging and call it from session, message, model, tool, permission, and artifact services with redaction.
- Risk if ignored: Security investigations will miss who prompted, which model was called, and what data was exposed.

### Plugin system
- Current problem: Database rows may imply a capability that runtime does not provide
- Why it matters: Unsafe plugin execution would be a critical vulnerability if added casually.
- Exact file(s): `backend/app/plugins/loader.py`
- Exact recommended fix: Define plugin manifest and trust model before enabling execution; start with signed/local metadata only.
- Risk if ignored: Unsafe plugin execution would be a critical vulnerability if added casually.

### MCP integration
- Current problem: MCP rows cannot be used by agents
- Why it matters: Later MCP could bypass permission/audit if not wrapped through ToolExecutor.
- Exact file(s): `backend/app/mcp/client.py`
- Exact recommended fix: Implement MCP client with tool discovery feeding ToolRegistry and permission/audit wrapping.
- Risk if ignored: Later MCP could bypass permission/audit if not wrapped through ToolExecutor.

### GitHub workflow/bot integration
- Current problem: None for current target if GitHub automation remains out of scope
- Why it matters: If later added, repository write permissions need separate auth/approval design.
- Exact file(s): `docs/architecture/github-integration.md`
- Exact recommended fix: Ignore for now and revisit as a separate integration after core runtime safety.
- Risk if ignored: If later added, repository write permissions need separate auth/approval design.

### CLI client
- Current improvement: CLI is now a package with Typer commands for health, agents, sessions, chat, queue status, artifacts, and a minimal Rich TUI; tests cover the client, parser, renderers, permission prompts, human-input prompts, and diff preview.
- Why it matters: Operators can use the runtime from a terminal when the web UI is not ideal or not available.
- Exact file(s): `backend/app/cli/main.py`, `backend/app/cli/api_client.py`, `backend/app/cli/websocket_client.py`, `backend/app/cli/tui_app.py`, `backend/tests/test_cli_flow.py`.
- Exact recommended next fix: upgrade the minimal Rich loop to a full modal TUI with better session switching, replay cursors, and richer message-part rendering.
- Risk if ignored: Batch 1 is usable, but the terminal UX will still feel more like an operator console than a polished full-screen coding workspace.

### Security model
- Current problem: Bootstrap user creates single-user behavior; APIs are not protected by auth boundaries
- Why it matters: Anyone with backend network access can create sessions and run ask-approved tools.
- Exact file(s): `backend/app/core/security.py`
- Exact recommended fix: Add local auth/token model and enforce tenant ownership in every route before services run.
- Risk if ignored: Anyone with backend network access can create sessions and run ask-approved tools.

## Frontend

### Agent context building
- Current problem: Transcript-only context degrades quickly; Tool results are raw JSON text
- Why it matters: Long sessions become unreliable and local models lose operational context.
- Exact file(s): `backend/app/runtime/context_builder.py`
- Exact recommended fix: Create context builder selecting recent messages, summaries, tool results, workspace metadata, and memory snippets under a budget.
- Risk if ignored: Long sessions become unreliable and local models lose operational context.
### TUI client

- Current improvement: A Textual full-screen TUI (`AgentPlatformTuiApp`) with a pure-Python state reducer (`tui_state.py`) and a WebSocket event bridge (`tui_events.py`) now drives a header/health bar, left session list, center message panel + event log, right tool timeline + summary, bottom prompt composer, and modal screens for permission / human-input / agent-switcher / session-create flows. Keybindings: `ctrl+c` quit, `ctrl+n` new session, `ctrl+s` focus sessions, `ctrl+a` switch agent, `ctrl+r` retry, `ctrl+d` show diff, `ctrl+l` clear messages, `ctrl+t` toggle events. The CLI also gained `agentv2 tui --check` for non-interactive CI smoke. The Rich-based `tui_modals.py` from Batch 2 is retained as a fallback renderer for the legacy import surface. See `docs/opencode-study/implementation-roadmap.md` for the CLI/TUI Coding Flow Batch 3 result.
- Why it matters: Headless users can drive the platform from a true full-screen terminal coding workspace with a real event stream and a tested state machine.
- Exact file(s): `backend/app/cli/tui_app.py`, `backend/app/cli/tui_state.py`, `backend/app/cli/tui_events.py`, `backend/app/cli/tui_modals.py`, `backend/app/cli/main.py`, `backend/tests/test_tui_state.py`, `backend/tests/test_tui_events.py`, `backend/tests/test_cli_flow.py`, `scripts/cli-tui-smoke.ps1`, `docs/opencode-study/flow-parity-matrix.json`, `docs/opencode-study/100-opencode-flow-parity-roadmap.md`, `docs/opencode-study/implementation-roadmap.md`, `README.md`.
- Exact recommended next fix: split the event log into a tabbed view (events / tool calls / queue), persist the TUI layout across restarts, and add a notification bar that surfaces pending permission / human-input requests before the modal pops.
- Risk if ignored: Terminal users still get a real workspace, but the event log mixes types and the layout state is not persisted.

### Web UI dashboard
- Current problem: Dashboard.tsx is a large single component; Polling and WebSocket state are mixed into one page
- Why it matters: Feature growth will make the UI hard to maintain.
- Exact file(s): `frontend/src/pages/Dashboard.tsx`
- Exact recommended fix: Split Dashboard into page components and shared stores before adding more runtime UI.
- Risk if ignored: Feature growth will make the UI hard to maintain.

### Session detail/chat UI
- Current problem: Chat uses general agent with edit tools; Error state can reflect protocol fallback instead of clear mode
- Why it matters: Users may expect safe chat but start a tool-capable session.
- Exact file(s): `frontend/src/pages/Dashboard.tsx`
- Exact recommended fix: Create a dedicated chat-safe agent/profile and render structured message/tool/permission parts.
- Risk if ignored: Users may expect safe chat but start a tool-capable session.

### Model status UI
- Current problem: Cloud-looking Ollama tags are not labeled but remain selectable by user requirement; Model size unknown renders plainly
- Why it matters: Users cannot tell which models are tool-capable or currently reachable beyond dependency health.
- Exact file(s): `frontend/src/pages/Dashboard.tsx`
- Exact recommended fix: Add model detail labels from provider capability metadata without filtering selectable Ollama tags.
- Risk if ignored: Users cannot tell which models are tool-capable or currently reachable beyond dependency health.

### Logs/events UI
- Current problem: Events tab renders raw JSON and can grow noisy; No correlation view across run/model/tool
- Why it matters: Operators cannot quickly diagnose failed runs in production.
- Exact file(s): `frontend/src/pages/EventsPage.tsx`
- Exact recommended fix: Split events page with filters, detail drawer, and correlation IDs.
- Risk if ignored: Operators cannot quickly diagnose failed runs in production.

## Infra

### ClickHouse/event analytics
- Current problem: ClickHouse is infrastructure-only and not connected to SystemEvent
- Why it matters: Observability promises are not fulfilled and system_events may grow without analytics offload.
- Exact file(s): `backend/app/analytics/event_writer.py`
- Exact recommended fix: Define ClickHouse event table and mirror SystemEvent rows asynchronously.
- Risk if ignored: Observability promises are not fulfilled and system_events may grow without analytics offload.

### Docker/dependency orchestration
- Current problem: Default service passwords are development-grade; ollama_data volume remains declared although Docker Ollama is optional
- Why it matters: Developers may mistake dev Compose for production deployment.
- Exact file(s): `docker-compose.yml`
- Exact recommended fix: Add dev/production compose profiles and a worker service once queue runtime exists.
- Risk if ignored: Developers may mistake dev Compose for production deployment.

### Health checks
- Current problem: Backend Docker health only checks /health; Detailed errors may expose internal endpoints
- Why it matters: Orchestrators can route traffic to an app whose dependencies are degraded.
- Exact file(s): `backend/app/api/routes_health.py`
- Exact recommended fix: Add /health/live and /health/ready with migration/dependency readiness and sanitized output.
- Risk if ignored: Orchestrators can route traffic to an app whose dependencies are degraded.

## Database

### Storage/database schema
- Current problem: Some common query IDs lack indexes; updated_at relies on ORM/raw defaults without triggers
- Why it matters: Integrity bugs can appear under concurrent and multi-tenant usage.
- Exact file(s): `backend/app/db/migrations/versions/202606050002_integrity_constraints.py`
- Exact recommended fix: Add constraints, FK links, enums/checks, and tenant-aware indexes.
- Risk if ignored: Integrity bugs can appear under concurrent and multi-tenant usage.

### Migrations
- Current problem: Initial migration is large and raw SQL-heavy; No model-vs-migration drift check
- Why it matters: Future schema changes can drift silently from SQLAlchemy models.
- Exact file(s): `backend/tests/test_migrations.py`
- Exact recommended fix: Add migration smoke tests and model-vs-migration drift checks.
- Risk if ignored: Future schema changes can drift silently from SQLAlchemy models.

### Artifact storage
- Current problem: ArtifactService is list-only; ToolResult.artifacts are not normalized after execution
- Why it matters: Large outputs and generated files remain trapped in text or local filesystem.
- Exact file(s): `backend/app/artifacts/artifact_service.py`
- Exact recommended fix: Implement MinIO put/get/presign and persist ToolResult.artifacts from ToolExecutor.
- Risk if ignored: Large outputs and generated files remain trapped in text or local filesystem.

### Memory/vector storage
- Current problem: Vector dimension fixed at 1536 without Ollama embedding decision; memory_service.py is empty
- Why it matters: Memory infrastructure exists but agents cannot use it.
- Exact file(s): `backend/app/memory/memory_service.py`
- Exact recommended fix: Implement memory ingestion/retrieval and inject snippets into context builder.
- Risk if ignored: Memory infrastructure exists but agents cannot use it.

### Graph storage
- Current problem: Neo4j is operationally present but unused
- Why it matters: Graph service consumes resources without platform behavior.
- Exact file(s): `backend/app/memory/graph_store.py`
- Exact recommended fix: Define graph nodes and relationships for projects, files, symbols, sessions, tools, and workflows.
- Risk if ignored: Graph service consumes resources without platform behavior.

## Agent runtime

### Agent run model
- Current problem: Runs execute inside HTTP requests; waiting_permission has no resume entrypoint
- Why it matters: Long or permission-blocked runs can be lost or require manual re-prompting.
- Exact file(s): `backend/app/runtime/agent_runner.py`
- Exact recommended fix: Persist run state transitions and add a resume path invoked by approval or worker scheduling.
- Risk if ignored: Long or permission-blocked runs can be lost or require manual re-prompting.

### Agent runtime loop
- Current problem: Runs happen inside request/response; Context is unbudgeted transcript; Tool failure ends run instead of allowing correction
- Why it matters: Production users will see blocked HTTP requests and brittle local model tool behavior.
- Exact file(s): `backend/app/runtime/agent_runner.py`
- Exact recommended fix: Refactor into a resumable state machine and queue-backed worker while preserving strict JSON for Ollama tool mode.
- Risk if ignored: Production users will see blocked HTTP requests and brittle local model tool behavior.

### Agent step limits
- Current problem: Max-step failure is generic; No event emitted for each step
- Why it matters: Agents can stop abruptly without useful recovery guidance.
- Exact file(s): `backend/app/runtime/agent_runner.py`
- Exact recommended fix: Emit step events and inject a final-step reminder before the last model call.
- Risk if ignored: Agents can stop abruptly without useful recovery guidance.

### Compaction/summarization
- Current problem: Hidden agents imply a capability that is unreachable
- Why it matters: Long sessions eventually fail or become incoherent.
- Exact file(s): `backend/app/runtime/compaction_service.py`
- Exact recommended fix: Implement summary storage and /sessions/{id}/compact without deleting original messages.
- Risk if ignored: Long sessions eventually fail or become incoherent.

### Queue/worker runtime
- Current problem: HTTP request blocks during model/tool loop; Permission waits return before a worker can resume
- Why it matters: Runs cannot survive restarts or scale horizontally.
- Exact file(s): `backend/app/queue/worker.py`
- Exact recommended fix: Move agent execution into Redis-backed worker with locks and resumable jobs.
- Risk if ignored: Runs cannot survive restarts or scale horizontally.

### Production-readiness
- Current problem: Architecture is production-shaped but not production-hardened; Several infrastructure services are health-checked but unused
- Why it matters: Calling it production-ready now would overstate maturity and create operational/security risk.
- Exact file(s): `docs/opencode-study/implementation-roadmap.md`
- Exact recommended fix: Execute the P0 roadmap before adding new feature surface area.
- Risk if ignored: Calling it production-ready now would overstate maturity and create operational/security risk.

## Tools

### Tool call model
- Current problem: permission_request_id is not a foreign key; waiting_permission rows can remain stuck
- Why it matters: Audit history can show approval while the original tool never executed.
- Exact file(s): `backend/app/db/models.py`
- Exact recommended fix: Add FK constraints, normalized status enums, and resume metadata for waiting tool calls.
- Risk if ignored: Audit history can show approval while the original tool never executed.

### Tool registry
- Current problem: Registry is process-static; OpenCode-to-Python tool mapping is not exposed in API docs
- Why it matters: Extensibility is blocked until trusted dynamic tool sources are supported.
- Exact file(s): `backend/app/tools/registry.py`
- Exact recommended fix: Add reloadable registry providers for plugin/MCP tools while preserving typed Pydantic boundaries.
- Risk if ignored: Extensibility is blocked until trusted dynamic tool sources are supported.

### Tool metadata/schema validation
- Current problem: Validation failures do not always emit TOOL_CALL_FAILED; Output schema is generic for all tools
- Why it matters: Local models receive sparse tool guidance and call tools incorrectly.
- Exact file(s): `backend/app/tools/base.py`
- Exact recommended fix: Add schema_version/examples and standardize invalid input feedback.
- Risk if ignored: Local models receive sparse tool guidance and call tools incorrectly.

### File read tool
- Current problem: Binary preview can leak sensitive bytes after approval; Directory listing lacks stat metadata
- Why it matters: Symlink or secret file paths can expose data unexpectedly.
- Exact file(s): `backend/app/tools/read.py`
- Exact recommended fix: Add secret path detection and symlink escape checks before reading.
- Risk if ignored: Symlink or secret file paths can expose data unexpectedly.

### File write tool
- Current problem: Parent directories are created once permission is approved without separate context; No file mode preservation
- Why it matters: Approved writes can overwrite critical files without diff preview or rollback.
- Exact file(s): `backend/app/tools/write.py`
- Exact recommended fix: Add diff preview metadata, atomic write, symlink/secret checks, and approval resume integration.
- Risk if ignored: Approved writes can overwrite critical files without diff preview or rollback.

### Edit/patch tool
- Current problem: Patch update can mishandle context; Edit only supports exact substring replacement
- Why it matters: Patch application can corrupt files or fail on common diffs.
- Exact file(s): `backend/app/tools/patch.py`
- Exact recommended fix: Replace simple parser with a tested patch engine and store before/after diff metadata.
- Risk if ignored: Patch application can corrupt files or fail on common diffs.

### Bash/shell tool
- Current problem: Shell expansion is enabled; External effects depend heavily on manual approval
- Why it matters: Shell execution is the highest-risk tool and currently too broad.
- Exact file(s): `backend/app/tools/bash.py`
- Exact recommended fix: Add shell policy with safe parsing, env scrub, cwd enforcement, and explicit exit-code handling.
- Risk if ignored: Shell execution is the highest-risk tool and currently too broad.

### Grep/search tool
- Current problem: Fallback traversal can be slow; Regex errors are not normalized
- Why it matters: Large repositories can make search slow or noisy.
- Exact file(s): `backend/app/tools/grep.py`
- Exact recommended fix: Normalize regex errors and add include/exclude/gitignore options.
- Risk if ignored: Large repositories can make search slow or noisy.

### Glob tool
- Current problem: pathlib semantics may differ from fast-glob expectations; No directory size guard
- Why it matters: Models can miss files or scan too much in large workspaces.
- Exact file(s): `backend/app/tools/glob.py`
- Exact recommended fix: Define glob semantics and ignore behavior matching platform expectations.
- Risk if ignored: Models can miss files or scan too much in large workspaces.

### Todo tool
- Current problem: Tool says update but only returns metadata; Todos disappear from prominent UI after scroll
- Why it matters: Users cannot trust todo state as a runtime planning artifact.
- Exact file(s): `backend/app/runtime/todo_service.py`
- Exact recommended fix: Persist latest todo list per session and expose it in session detail.
- Risk if ignored: Users cannot trust todo state as a runtime planning artifact.

### Question/human input tool
- Current problem: Tool output claims UI recording that does not exist
- Why it matters: Agents that ask clarifying questions cannot receive answers through the runtime.
- Exact file(s): `backend/app/runtime/question_service.py`
- Exact recommended fix: Implement question lifecycle parallel to permission requests with answer resume.
- Risk if ignored: Agents that ask clarifying questions cannot receive answers through the runtime.

### Environment/secret file protection
- Current problem: Workspace .env is currently normal read.file because read.file is allowed
- Why it matters: Secrets can be read into model prompts, persisted, and displayed in UI.
- Exact file(s): `backend/app/permissions/secret_policy.py`
- Exact recommended fix: Implement secret path/content detection and redact sensitive values in tool/model/audit payloads.
- Risk if ignored: Secrets can be read into model prompts, persisted, and displayed in UI.

### Agent/tool management UI
- Current problem: Tool schemas are not expandable; Hidden agents are not manageable
- Why it matters: Operators cannot safely tune runtime without editing code.
- Exact file(s): `frontend/src/pages/AgentsPage.tsx`
- Exact recommended fix: Split management pages and add read-only detail drawers before config APIs.
- Risk if ignored: Operators cannot safely tune runtime without editing code.

## Permissions

### Permission engine
- Current problem: matcher.py exists but policy uses fixed rules; Resolved permissions do not trigger execution
- Why it matters: Permission prompts are auditable but operationally incomplete.
- Exact file(s): `backend/app/permissions/service.py`
- Exact recommended fix: Add saved approval rules and invoke run resume when a request is approved.
- Risk if ignored: Permission prompts are auditable but operationally incomplete.

### Permission request/approval flow
- Current problem: Approval returns only permission row; Denied request does not mark linked tool_call failed
- Why it matters: Users can click Approve and still see the run stuck.
- Exact file(s): `backend/app/api/routes_permissions.py`
- Exact recommended fix: Resolve linked tool/run state inside approve/deny and schedule/resume execution.
- Risk if ignored: Users can click Approve and still see the run stuck.

### Permission UI integration
- Current problem: UI shows key/resource but not full risk context; Chat sidecar can miss global prompts
- Why it matters: Users may approve risky operations without enough context or believe approval executed when it did not.
- Exact file(s): `frontend/src/pages/Dashboard.tsx`
- Exact recommended fix: Add permission detail cards/modal with input preview and once/always/deny choices tied to backend resume.
- Risk if ignored: Users may approve risky operations without enough context or believe approval executed when it did not.

### External directory protection
- Current problem: Comma-split resource parsing can mis-handle commas in paths; Shell commands are not path-parsed
- Why it matters: Some external access can slip through shell commands or symlinks.
- Exact file(s): `backend/app/permissions/policy.py`
- Exact recommended fix: Centralize resolved path authority checks and call it from every file and shell tool.
- Risk if ignored: Some external access can slip through shell commands or symlinks.

### Permission prompt UI
- Current problem: Prompt context is too thin for destructive operations; Buttons can be clicked repeatedly
- Why it matters: Users may approve without understanding effect or get stuck after approval.
- Exact file(s): `frontend/src/components/PermissionPrompt.tsx`
- Exact recommended fix: Add reusable permission prompt component with preview, risk labels, and once/always/deny actions.
- Risk if ignored: Users may approve without understanding effect or get stuck after approval.

## Model provider

### Model provider abstraction
- Current problem: ModelProvider table is not used by routing; Provider errors mostly pass through httpx
- Why it matters: Even Ollama-only routing needs capabilities and health state for safe model selection.
- Exact file(s): `backend/app/providers/base.py`
- Exact recommended fix: Formalize provider capabilities and persist provider/model health snapshots.
- Risk if ignored: Even Ollama-only routing needs capabilities and health state for safe model selection.

### Ollama/local model support
- Current problem: All models are treated as JSON-capable tool users; num_predict default is low for substantive chat
- Why it matters: Some Ollama tags will chat but fail tool protocol or truncate responses.
- Exact file(s): `backend/app/providers/ollama.py`
- Exact recommended fix: Add model capability metadata and separate plain chat mode from strict tool JSON mode.
- Risk if ignored: Some Ollama tags will chat but fail tool protocol or truncate responses.

## Tests

### Testing coverage
- Current problem: Several tests validate serializers/helpers rather than DB behavior; No CI config evident
- Why it matters: Core agent safety regressions can ship unnoticed.
- Exact file(s): `backend/tests/test_permission_resume.py`
- Exact recommended fix: Add high-risk integration tests first: permission resume, mutation tools, context builder, migrations, and frontend chat model picker.
- Risk if ignored: Core agent safety regressions can ship unnoticed.

## Docs

- No specific polish item identified in this audit.

# P0 Foundation Batch 1 Implementation Result

## Backend

- Implemented nested environment-backed settings in `backend/app/core/config.py` with production validation and compatibility properties for existing call sites.
- Polished ORM runtime records in `backend/app/db/models.py` and migration `backend/app/db/migrations/versions/202606050002_runtime_spine.py` to link model calls, tool calls, and system events to tenant/session/run/tool scope.
- Remaining polish: add Postgres migration integration tests and ready/liveness checks that prove migrations have run.

## Agent runtime

- Implemented `backend/app/runtime/context_builder.py` with bounded context, strict JSON protocol, allowed tool schemas, and compaction-needed signaling.
- Reworked `backend/app/runtime/agent_runner.py` to use the context builder, persist model calls, emit step events, fail after one JSON repair attempt, persist tool results, and stop at max steps.
- Remaining polish: add capability-aware model routing so non-JSON-friendly Ollama models can use a plain chat path instead of strict tool protocol.

## Events and WebSocket

- Implemented richer persisted event envelopes in `backend/app/runtime/event_bus.py`.
- Updated `backend/app/api/websocket.py`, `backend/app/api/routes_sessions.py`, and `backend/app/api/routes_system_events.py` to expose consistent event shape and WebSocket replay.
- Remaining polish: replace process-local live delivery with Redis pub/sub for multi-worker deployments.

## Tools and permissions

- Updated `backend/app/runtime/tool_executor.py` to persist requested/denied/invalid/unknown tool calls, emit `tool_call.requested`, store duration, and link events to run/tool IDs.
- Updated `backend/app/runtime/loop_guard.py` to use configurable max repeat limits.
- Remaining polish: approval flow still does not resume paused runs; external directory and secret-file protections need centralized hardening before mutation tools are production-safe.

## Tests

- Added focused tests for config, context builder, event bus, ORM mapping, Ollama chat/generate, native agent definitions, and agent runner final/tool/invalid/max-step paths.
- Validation run: `.venv/bin/pytest backend/tests` passed with 31 tests; `.venv/bin/python -m compileall backend/app` passed.
- Remaining polish: add Postgres-backed tests for migrations and tool-call persistence, plus WebSocket integration tests using FastAPI TestClient.

# P0 Foundation Batch 2 Implementation Result

## Backend

- Implemented permission approve/deny lifecycle in `backend/app/permissions/service.py`.
- Approval now resumes the paused run through `backend/app/runtime/agent_runner.py` and executes the exact stored pending tool call through `backend/app/runtime/tool_executor.py`.
- Denial now marks permission, tool call, agent run, and session state explicitly and emits permission/tool/run events.
- Remaining polish: move long-running resumed execution to a queue worker once Redis/worker runtime is implemented.

## Permissions

- Implemented one-shot request semantics: pending requests can be approved or denied once; approved/denied requests cannot be reused.
- Added input hash and payload validation before resume.
- Added `permission.resume_blocked` event and audit record for mismatched linked state.
- Remaining polish: add saved approval rules and richer UI-level once/always/deny choices.

## Tools

- Hardened path policy in `backend/app/permissions/policy.py`.
- Added secret path decisions for `.env`, credentials, tokens, private keys, and common secret filename patterns.
- Updated grep/glob/patch resource reporting so policy receives resolved filesystem paths.
- Remaining polish: add secret content redaction and shell command path/env scrubbing.

## Events

- Added optional Redis pub/sub delivery in `backend/app/runtime/event_bus.py`.
- Events still persist to Postgres first.
- Local mode remains available for tests and single-worker development.
- Remaining polish: run WebSocket and Redis pub/sub tests against a live Redis service in Docker.

## Model provider

- Added Ollama model capability metadata and selection in `backend/app/providers/base.py` and `backend/app/providers/router.py`.
- Added per-agent configured model fallback and disabled/non-JSON model handling.
- Updated `/models` to include capability metadata.
- Remaining polish: validate real model JSON behavior over time and store model health/capability snapshots in the database.

## Database

- Added `scripts/db-migration-smoke.sh` and `backend/tests/test_migrations_postgres.py`.
- Migration smoke is real-Postgres only and skips unless `AP_TEST_POSTGRES_URL` is configured.
- Remaining polish: add a dedicated test Postgres service or CI job to run the migration smoke automatically.

## Tests

- Added permission resume, policy hardening, Redis event publish path, model capability, and migration smoke tests.
- Final validation: `.venv/bin/pytest backend/tests` passed with 46 tests and 1 skipped migration test.
- Ruff now passes with `.venv/bin/python -m ruff check backend/app backend/tests`.

# P0 Foundation Batch 3 Implementation Result

## Frontend

- Implemented permission prompt UI in `frontend/src/components/PermissionPrompt.tsx` and wired it into `frontend/src/pages/Dashboard.tsx`.
- Implemented reusable runtime display components in `frontend/src/components/MessageList.tsx`, `frontend/src/components/ToolCallTimeline.tsx`, and `frontend/src/components/EventStream.tsx`.
- Added a reconnecting WebSocket helper in `frontend/src/api/sessionSocket.ts`.
- Updated `frontend/src/api/client.ts` with typed permission approve/deny, session event, session detail, agent, model, and dependency response shapes.
- Remaining polish: add a frontend test runner and component tests for permission prompt double-click prevention and socket reconnect behavior.

## Backend

- Added centralized redaction in `backend/app/core/redaction.py`.
- Applied redaction in `backend/app/runtime/event_bus.py`, `backend/app/runtime/tool_executor.py`, `backend/app/runtime/agent_runner.py`, `backend/app/runtime/session_service.py`, `backend/app/providers/ollama.py`, `backend/app/tools/read.py`, and `backend/app/api/routes_permissions.py`.
- Hardened bash execution in `backend/app/tools/bash.py` and destructive command policy in `backend/app/permissions/policy.py`.
- Remaining polish: move permission approval resume to a worker queue and add deeper shell intent parsing for script indirection.

## Security

- Current improvement: env assignments, bearer tokens, private key blocks, sensitive JSON keys, and long token-like strings are redacted before persistence/events/API display.
- Why it matters: runtime events, tool outputs, model call metadata, and session detail responses are no longer easy secret exfiltration surfaces.
- Exact follow-up: make redaction patterns configurable per organization and add fixtures for real `.env`, cloud key, SSH key, and package-manager token formats.
- Risk if ignored: new token formats may still leak until explicit regression tests are added.

## Infra

- Added `scripts/runtime-smoke.sh` and fixed `scripts/db-migration-smoke.sh` URL normalization.
- Live validation passed with `AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/runtime-smoke.sh`.
- Remaining polish: add a multi-backend Docker smoke that proves Redis pub/sub fanout across two backend workers.

## Tests

- Added `backend/tests/test_bash_safety.py`.
- Added `backend/tests/test_redaction.py`.
- Final Batch 3 validation passed: backend tests, compileall, ruff, frontend build/typecheck, and live runtime smoke.

# P0 Foundation Batch 4 Implementation Result

## Backend

- Current improvement: agent execution and permission approval resume can now run through a Redis-backed queue instead of inline API execution.
- Why it matters: API requests return quickly, long model/tool work moves to a worker process, and the architecture is closer to a production multi-worker runtime.
- Exact files: `backend/app/api/routes_messages.py`, `backend/app/api/routes_permissions.py`, `backend/app/runtime/agent_runner.py`, `backend/app/queue/jobs.py`, `backend/app/queue/worker.py`.
- Exact recommended next fix: add a persistent `queue_jobs` table for job attempts, last error, dead-letter state, locked worker identity, and operator retry controls.
- Risk if ignored: queue state is recoverable through events and run status, but operators cannot inspect or replay failed jobs from a first-class database record.

## Infra

- Current improvement: `docker-compose.yml` now includes a `backend-worker` service using the same backend image and queue worker entrypoint.
- Why it matters: local Docker now matches the intended API-plus-worker production topology.
- Exact files: `docker-compose.yml`, `.env.example`, `pyproject.toml`.
- Exact recommended next fix: add a Compose validation profile with two backend API replicas and a deterministic cross-process Redis/WebSocket fanout check.
- Risk if ignored: Redis pub/sub delivery is proven through the active backend, but true multi-backend fanout remains an operational assumption.

## Events

- Current improvement: queue and worker lifecycle events now include `agent_run.queued`, `agent_run.resume_queued`, `agent_run.resumed`, `agent_run.blocked`, `worker.started`, `worker.stopped`, `worker.job.failed`, and `worker.job.dead_lettered`.
- Why it matters: the UI and audit trail can distinguish queued, running, resumed, blocked, failed, and dead-lettered execution states.
- Exact files: `backend/app/core/events.py`, `backend/app/queue/jobs.py`, `backend/app/queue/worker.py`, `frontend/src/styles/app.css`.
- Exact recommended next fix: expose queue job/dead-letter summaries through a backend route and frontend operator view.
- Risk if ignored: dead-lettered work is visible in system events but not easy to triage from the dashboard.

## Permissions

- Current improvement: approval now validates and marks the request, then enqueues the stored permission resume job when queue mode is enabled.
- Why it matters: approved tool execution no longer blocks the approval HTTP request in the normal Docker/runtime path.
- Exact files: `backend/app/api/routes_permissions.py`, `backend/app/permissions/service.py`, `backend/app/queue/jobs.py`.
- Exact recommended next fix: add API contract tests that assert frontend-visible `resume_queued` state and add a live smoke that creates an actual ask/approve/resume flow against Docker.
- Risk if ignored: successful queued resume is unit-tested, but the live smoke currently covers the simple queued final-answer path rather than a real permission prompt.

## Agent runtime

- Current improvement: message submission creates exactly one queued run for a user message, publishes `agent_run.queued`, and the worker later publishes `agent_run.started` when it claims the job.
- Why it matters: run ownership is explicit and avoids duplicate inline/queued execution for one message.
- Exact files: `backend/app/runtime/agent_runner.py`, `backend/app/api/routes_messages.py`, `backend/tests/test_queue_jobs.py`.
- Exact recommended next fix: add worker concurrency controls and idempotency keys so duplicate Redis delivery cannot execute the same run twice.
- Risk if ignored: Redis list delivery is simple and reliable for this stage, but stronger idempotency will matter under worker crashes and retries.

## Tests

- Current improvement: `backend/tests/test_queue_jobs.py` covers dev fallback, production queue guard, Redis enqueue paths, worker execution, permission resume execution, failed job marking, and retry/dead-letter behavior.
- Why it matters: the queue spine has regression coverage without requiring live Redis for unit tests.
- Exact files: `backend/tests/test_queue_jobs.py`, `scripts/runtime-smoke.sh`, `scripts/redis-fanout-smoke.sh`.
- Exact recommended next fix: add a Docker-only integration test for an ask permission flow: write tool pauses, approve queues resume, worker executes, WebSocket receives completion.
- Risk if ignored: the most important permission-resume happy path is tested with mocked/in-process execution but not yet through the full Docker/WebSocket stack.

## Frontend

- Current improvement: queued, resume queued, resumed, and blocked statuses now have explicit styling and typed API response support.
- Why it matters: the UI no longer has to infer queue state from generic failed/running strings.
- Exact files: `frontend/src/api/client.ts`, `frontend/src/styles/app.css`.
- Exact recommended next fix: surface queue job IDs and dead-letter events in the session detail panel.
- Risk if ignored: users can see queued state, but cannot inspect the specific job envelope or retry history from the UI.

# P0 Foundation Batch 5 Implementation Result

## Database

- Current improvement: `queue_jobs` is now a durable runtime table with idempotency, attempt tracking, worker claim metadata, retry availability, completion/failure timestamps, and last error.
- Why it matters: Redis is no longer the source of truth for execution payloads; it is only a wake-up mechanism.
- Exact files: `backend/app/db/models.py`, `backend/app/db/migrations/versions/202606050003_queue_jobs.py`, `scripts/db-migration-smoke.sh`.
- Exact recommended next fix: add retention/archive policy for old completed queue jobs and indexes for operator search by `claimed_by` and `failed_at`.
- Risk if ignored: queue history can grow indefinitely and failed jobs will become harder to triage at scale.

## Queue

- Current improvement: enqueue is idempotent for agent runs and permission resumes, and Redis messages contain only `queue_job_id`.
- Why it matters: duplicate API calls or duplicate Redis messages no longer imply duplicate execution.
- Exact files: `backend/app/queue/jobs.py`, `backend/app/api/routes_messages.py`, `backend/app/api/routes_permissions.py`.
- Exact recommended next fix: add idempotency keys to API responses and document retry semantics for clients.
- Risk if ignored: backend behavior is safe, but API clients still lack explicit instructions for safe retries.

## Worker

- Current improvement: workers now claim jobs by durable DB status before execution, record `claimed_by`, transition through claimed/running/completed, retry failed jobs, and dead-letter after max attempts.
- Why it matters: multiple workers can consume the same Redis queue without executing the same completed job twice.
- Exact files: `backend/app/queue/worker.py`, `backend/app/queue/jobs.py`, `backend/tests/test_queue_jobs.py`.
- Exact recommended next fix: add periodic worker heartbeat updates and a configurable in-process concurrency limit.
- Risk if ignored: stale reclaim works after a timeout, but operators cannot distinguish a genuinely dead worker from a very long-running model call until the visibility window expires.

## Events

- Current improvement: queue job lifecycle events now include created, claimed, started, completed, failed, retry scheduled, and dead-lettered events.
- Why it matters: runtime execution can be reconstructed from persisted system events.
- Exact files: `backend/app/core/events.py`, `backend/app/queue/jobs.py`.
- Exact recommended next fix: add queue job event filtering to `/system/events` and the frontend events view.
- Risk if ignored: the raw events exist, but UI operators have to scan all system events manually.

## Permission Runtime

- Current improvement: live Docker permission resume smoke verifies approval, queued resume, worker execution, exactly-once tool completion, and required permission/run/tool events.
- Why it matters: this closes the largest prior gap between backend lifecycle tests and real Compose behavior.
- Exact files: `scripts/permission-resume-smoke.sh`, `backend/app/api/routes_permissions.py`, `backend/app/queue/jobs.py`.
- Exact recommended next fix: add a model-driven permission smoke once local model JSON tool-call compliance is reliable enough to avoid flaky infrastructure tests.
- Risk if ignored: deterministic smoke proves approval/resume execution, but not the model's ability to request the permission in the first place.

## Redis/WebSocket

- Current improvement: `scripts/redis-fanout-smoke.sh` now proves true two-backend fanout by starting backend B, connecting WebSocket to backend B, triggering `message.created` through backend A, and receiving the event through Redis on backend B.
- Why it matters: realtime events are no longer validated only inside a single API process.
- Exact files: `scripts/redis-fanout-smoke.sh`, `backend/app/runtime/event_bus.py`.
- Exact recommended next fix: make the two-backend setup a Compose profile or CI integration job instead of a script-spawned temporary process.
- Risk if ignored: the validation is real, but it is not yet part of a repeatable container topology with named services and health checks.

## Tests

- Current improvement: backend tests increased to 71 passed and 1 skipped, with queue idempotency, claim, stale reclaim, duplicate message dedupe, and dead-letter behavior covered.
- Why it matters: the highest-risk queue state transitions are now under regression tests.
- Exact files: `backend/tests/test_queue_jobs.py`, `backend/tests/test_db_models.py`, `backend/tests/test_migrations_postgres.py`.
- Exact recommended next fix: add real Postgres tests for `SELECT ... FOR UPDATE SKIP LOCKED` behavior when CI can provide a disposable database.
- Risk if ignored: fake-session tests cover intent, while the row-level lock behavior is currently proven through live smoke and code review rather than a dedicated concurrent Postgres test.

# Tool System Parity Batch 1 Implementation Result

## Backend tool contract

- Current improvement: native tools now expose full metadata and return a unified `ToolResult` shape with structured errors, redaction/truncation flags, artifacts, metadata, timestamps, and duration.
- Why it matters: OpenCode-style tool orchestration depends on typed schemas, user-visible metadata, and stable persisted results rather than arbitrary strings.
- Exact files: `backend/app/tools/base.py`, `backend/app/tools/registry.py`, `backend/app/api/routes_tools.py`, `backend/tests/test_tool_registry.py`.
- Exact recommended next fix: generate Markdown/API docs from `GET /tools` metadata and add a frontend tool detail panel that shows risk level, examples, and permission behavior.
- Risk if ignored: backend metadata exists, but users still need to inspect raw JSON or source files to understand tool behavior.

## Filesystem tools

- Current improvement: `read.file`, `write.file`, and `edit.file` now resolve real paths, enforce workspace boundaries, support stronger read/write/edit options, and return structured results.
- Why it matters: file tools are the highest-frequency agent tools and must be safe under symlinks, stale writes, binary files, and redacted content.
- Exact files: `backend/app/tools/read.py`, `backend/app/tools/write.py`, `backend/app/tools/edit.py`, `backend/tests/test_tool_parity.py`.
- Exact recommended next fix: add a shared path-safety helper that returns structured permission decisions for direct tool calls, so direct `.run()` behavior and executor behavior share identical failure envelopes.
- Risk if ignored: executor-managed runs persist structured failures, but direct tool invocation can still raise Python exceptions for some safety blocks.

## Patch tool

- Current improvement: `patch.apply` now validates workspace paths, refuses binary patches, supports dry-run mode, applies internal patches safely, and supports standard unified diff application through `patch`.
- Why it matters: patching is more powerful than single-file edits and needs stronger path traversal and preview behavior.
- Exact files: `backend/app/tools/patch.py`, `backend/tests/test_tool_parity.py`.
- Exact recommended next fix: replace shelling out to `patch` with a Python diff parser/applicator or wrap it with rollback protection for failed first-pass strip attempts.
- Risk if ignored: current behavior is safe for tested common patches, but very complex diffs rely on host `patch` behavior and may be harder to audit.

## Search tools

- Current improvement: `grep.search` and `glob.search` now support include/exclude filters, max result controls, stable output, context lines for grep, hidden-file control for glob, binary skipping, secret omission, and symlink-outside blocking.
- Why it matters: search output enters model context directly and must not leak secrets or explode context size.
- Exact files: `backend/app/tools/grep.py`, `backend/app/tools/glob.py`, `backend/tests/test_tool_parity.py`.
- Exact recommended next fix: add an optional ripgrep backend for large workspaces while preserving the exact structured output contract and secret filtering.
- Risk if ignored: Python search is correct and portable but may become slow on large monorepos.

## Shell tool

- Current improvement: `bash.run` now exposes structured classifier metadata, blocks destructive commands with `ToolResult.failure`, limits output, records exit status, and redacts captured output.
- Why it matters: shell execution is high-risk and must be auditable even when approved.
- Exact files: `backend/app/tools/bash.py`, `backend/tests/test_bash_safety.py`.
- Exact recommended next fix: add streaming output events behind a size cap and redact chunks before broadcast.
- Risk if ignored: completed shell output is safe, but long-running command progress is invisible until process exit.

## Planning and human-input tools

- Current improvement: `todo.write` supports replace/update semantics and persists session todos through executor side effects; `question.ask` gained a durable request, answer/cancel, timeout, UI, and queue-backed resume lifecycle in Batch 2.
- Why it matters: planning and human input are part of OpenCode-style collaborative agent control, not just file manipulation.
- Exact files: `backend/app/tools/todo.py`, `backend/app/tools/question.py`, `backend/app/runtime/tool_executor.py`, `backend/app/core/events.py`, `backend/tests/test_tool_parity.py`.
- Exact recommended next fix: add answered/cancelled/expired human-input history to the session detail UI and API.
- Risk if ignored: active questions work, but older human-input decisions are mostly visible through events and tool calls.

## Tests

- Current improvement: backend tests increased to 81 passed and 1 skipped, including registry metadata, disabled tool rejection, normalized failure shape, file read/write/edit safety, patch safety, grep/glob behavior, todo persistence, and redaction compatibility.
- Why it matters: the tool runtime has broad regression coverage before deeper agent-tool parity work.
- Exact files: `backend/tests/test_tool_registry.py`, `backend/tests/test_tool_parity.py`, `backend/tests/test_redaction.py`.
- Exact recommended next fix: add executor-level tests for every native tool so permission, audit logging, redaction, event emission, and persistence are verified together.
- Risk if ignored: direct tool tests catch tool behavior, but only some tools are currently covered through the full executor/audit/event path.

# Tool System Parity Batch 2 Implementation Result

## Human input runtime

- Current improvement: `question.ask` now creates durable `human_input_requests`, pauses runs with `waiting_human_input`, accepts answers/cancels through API, resumes via queue jobs, and completes the pending tool call with the human answer.
- Why it matters: human-in-the-loop agent control is now auditable and resumable instead of being a transient event.
- Exact files: `backend/app/db/models.py`, `backend/app/runtime/human_input_service.py`, `backend/app/runtime/tool_executor.py`, `backend/app/runtime/agent_runner.py`, `backend/app/queue/jobs.py`.
- Exact recommended next fix: add a persisted answer history/detail endpoint for non-pending requests and expose it in session detail.
- Risk if ignored: pending human input is usable, but answered/cancelled/expired request history is visible mainly through events and tool calls.

## Human input API

- Current improvement: added `GET /human-input/requests`, `POST /human-input/{id}/answer`, and `POST /human-input/{id}/cancel`, plus choice validation, double-answer blocking, cancellation, expiry enforcement, and queue-backed answer resume.
- Why it matters: UI and external clients can complete the human-input lifecycle without touching database internals.
- Exact files: `backend/app/api/routes_human_input.py`, `backend/app/main.py`.
- Exact recommended next fix: add route-level tests with dependency overrides for answer, cancel, invalid choice, and queue response contracts.
- Risk if ignored: service-level behavior is tested, but API dependency wiring has less direct regression coverage.

## Frontend

- Current improvement: added a dedicated `HumanInputPrompt` component and Chat/Session Detail rendering for pending human-input requests, with choices, free text, answer/cancel buttons, and loading guards.
- Why it matters: human prompts are no longer confused with permission prompts, and users can answer directly in the runtime UI.
- Exact files: `frontend/src/api/client.ts`, `frontend/src/components/HumanInputPrompt.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles/app.css`.
- Exact recommended next fix: show answered/cancelled/expired request history in the session detail sidebar or event timeline.
- Risk if ignored: active prompts are easy to handle, but past decisions require reading event rows.

## Expiry

- Current improvement: requests can include `timeout_seconds`; answering after `expires_at` marks the request expired, blocks the run, and emits `question.expired`.
- Why it matters: stale human-input waits cannot be answered silently after their contract expires.
- Exact files: `backend/app/runtime/human_input_service.py`, `backend/tests/test_human_input.py`.
- Exact recommended next fix: add a worker startup pass or periodic job that calls `human_input_service.expire_pending` so stale prompts expire even if nobody clicks answer.
- Risk if ignored: expiry is enforced on answer, but abandoned prompts can remain pending until touched.

## Smoke validation

- Current improvement: added `scripts/human-input-smoke.sh` and a production-disabled test seed path guarded by `AP_ENABLE_TEST_ENDPOINTS=true`.
- Why it matters: the smoke can deterministically validate answer API, queue resume, worker execution, event emission, and exactly-once tool completion without relying on model JSON reliability.
- Exact files: `scripts/human-input-smoke.sh`, `backend/app/api/routes_human_input.py`, `backend/app/core/config.py`, `docker-compose.yml`.
- Exact recommended next fix: run the smoke against Docker with `AP_ENABLE_TEST_ENDPOINTS=true AP_TEST_POSTGRES_URL=postgresql+psycopg://agent:agent@localhost:15432/agent_platform scripts/human-input-smoke.sh` and record the live result.
- Risk if ignored: unit tests prove behavior, but the live Docker worker path remains unverified in this shell because no Postgres test URL was set.

## Tests

- Current improvement: backend tests increased to 89 passed and 1 skipped, with coverage for durable request creation, pause state, answer/resume, cancel, double answer, invalid choice, expiry, queue idempotency, and worker resume.
- Why it matters: the new human-input state machine is under regression coverage before broader agent/runtime work continues.
- Exact files: `backend/tests/test_human_input.py`, `backend/tests/test_db_models.py`, `backend/tests/test_migrations_postgres.py`.
- Exact recommended next fix: add real Postgres migration smoke for `human_input_requests` in CI and API route tests for `/human-input`.
- Risk if ignored: fake-session tests cover service behavior; live DB/HTTP coverage still depends on smoke execution.

# Memory + Compaction Parity Batch 1 Implementation Result

## Database

- Current improvement: added `session_summaries` and upgraded `memory_items` with source typing, content-hash dedupe, visibility, status, embedding metadata, and migration smoke checks.
- Why it matters: long sessions now have durable context state instead of relying only on ad hoc message metadata.
- Exact files: `backend/app/db/models.py`, `backend/app/db/migrations/versions/202606050005_memory_compaction.py`, `scripts/db-migration-smoke.sh`.
- Exact recommended next fix: run `scripts/db-migration-smoke.sh` against Docker Postgres and add a CI job with `AP_TEST_POSTGRES_URL`.
- Risk if ignored: unit tests verify model shape, but real migration validation remains opt-in unless CI runs it.

## Summary service

- Current improvement: `summary_service` creates active summaries, fetches active/latest summaries, supersedes active summaries, records failed attempts, and emits summary lifecycle events.
- Why it matters: compaction can fail safely without corrupting the session’s active context.
- Exact files: `backend/app/memory/summary_service.py`, `backend/tests/test_memory_compaction.py`.
- Exact recommended next fix: add route-level tests for `POST /sessions/{id}/summaries` using dependency overrides.
- Risk if ignored: service behavior is covered, but HTTP contract regressions could slip through until OpenAPI/runtime smoke catches them.

## Memory service

- Current improvement: `memory_service` supports scoped creation, dedupe by content hash, text search fallback, visibility filtering, summary-to-memory persistence, and explicit embedding-disabled metadata.
- Why it matters: retrieval now works in a degraded, honest mode without fake embeddings.
- Exact files: `backend/app/memory/memory_service.py`, `backend/app/memory/pgvector_store.py`, `backend/app/memory/qdrant_store.py`.
- Exact recommended next fix: add an integration test with a real Ollama embedding model and pgvector nearest-neighbor query once an embedding model is selected.
- Risk if ignored: text memory works, but vector retrieval remains infrastructure-ready rather than production-validated.

## Agent runtime

- Current improvement: `AgentRunner` can create manual/model summaries, run queue-backed compaction, persist summaries, write summary memory items, and emit compaction lifecycle events.
- Why it matters: context pressure no longer has to be handled by dumping the full session history into a prompt.
- Exact files: `backend/app/runtime/agent_runner.py`, `backend/app/queue/jobs.py`.
- Exact recommended next fix: add a real Docker smoke run with `AP_ENABLE_TEST_ENDPOINTS=true AP_TEST_POSTGRES_URL=... scripts/memory-compaction-smoke.sh`.
- Risk if ignored: mocked tests prove behavior, but the live worker path is only exercised once the smoke has a database URL.

## Context builder

- Current improvement: context now prioritizes active summaries, then relevant memory, then recent messages under the existing character budget and reports compaction pressure.
- Why it matters: local models get stable state without unbounded transcript growth.
- Exact files: `backend/app/runtime/context_builder.py`, `backend/tests/test_context_builder.py`, `backend/tests/test_memory_compaction.py`.
- Exact recommended next fix: tune summary/memory selection with relevance scoring once embeddings are enabled.
- Risk if ignored: fallback selection is deterministic and safe, but may include less relevant memory in large projects.

## Frontend

- Current improvement: session detail displays active session summaries in a compact panel.
- Why it matters: users can see what the runtime is carrying forward after compaction.
- Exact files: `frontend/src/api/client.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles/app.css`.
- Exact recommended next fix: add a dedicated memory/summaries tab or drawer with active/superseded/failed filters.
- Risk if ignored: active summaries are visible, but memory/debug inspection remains shallow.

## Smoke validation

- Current improvement: added `scripts/memory-compaction-smoke.sh` with a guarded non-production queue-backed seed path.
- Why it matters: compaction can be validated without relying on local model JSON reliability.
- Exact files: `scripts/memory-compaction-smoke.sh`, `backend/app/api/routes_memory.py`, `backend/app/runtime/agent_runner.py`.
- Exact recommended next fix: run the smoke against the Docker stack with `AP_ENABLE_TEST_ENDPOINTS=true`, `AP_QUEUE_ENABLED=true`, backend worker running, and a real `AP_TEST_POSTGRES_URL`.
- Risk if ignored: the smoke exists and fails honestly, but live Docker proof is still pending in this shell.

## Tests

- Current improvement: backend tests increased to 99 passed and 1 skipped, covering model mappings, summaries, memory dedupe/search, context inclusion, compaction jobs, mocked summary failure, worker compaction, and OpenAPI paths.
- Why it matters: the memory/compaction runtime has broad regression coverage before vector and Qdrant work deepens.
- Exact files: `backend/tests/test_memory_compaction.py`, `backend/tests/test_db_models.py`, `backend/tests/test_migrations_postgres.py`.
- Exact recommended next fix: add real Postgres row checks for `session_summaries` and memory indexes in migration CI.
- Risk if ignored: fake-session tests cover behavior, but lock/index/migration behavior needs real database validation.

# Code Intelligence + LSP Parity Batch 1 Implementation Result

## Database

- Current improvement: added `code_files`, `code_symbols`, `code_references`, and `code_diagnostics` with migration and migration-smoke table checks.
- Why it matters: code intelligence now has durable, queryable state instead of transient scans.
- Exact files: `backend/app/db/models.py`, `backend/app/db/migrations/versions/202606050006_code_intelligence.py`, `scripts/db-migration-smoke.sh`.
- Exact recommended next fix: run migration smoke against Docker Postgres and add index/constraint checks for code-intelligence tables.
- Risk if ignored: unit tests verify mapping shape, but real DB index/constraint behavior remains opt-in.

## Indexer

- Current improvement: added workspace-rooted static indexing with language detection, Python AST symbols, TypeScript/JavaScript regex fallback, Markdown heading symbols, change detection, and ignore patterns.
- Why it matters: agents can reason over repository structure without reading arbitrary files or dumping source into prompts.
- Exact files: `backend/app/codeintel/indexer.py`, `backend/app/codeintel/language.py`, `backend/app/codeintel/parser.py`, `backend/tests/test_codeintel.py`.
- Exact recommended next fix: add a queue-backed indexing job for large workspaces and heartbeat/progress events for long scans.
- Risk if ignored: synchronous indexing is acceptable for MVP but can block request latency on large repositories.

## LSP

- Current improvement: added an honest static fallback adapter for definitions, references, diagnostics, and symbols.
- Why it matters: API/tool contracts exist without falsely claiming real language-server semantics.
- Exact files: `backend/app/codeintel/lsp_client.py`, `backend/app/api/routes_codeintel.py`.
- Exact recommended next fix: wire optional JSON-RPC language server lifecycle with explicit configuration, process supervision, timeout handling, and degraded health when unavailable.
- Risk if ignored: static fallback remains useful but cannot provide semantic references, type-aware definitions, or live diagnostics.

## Tools

- Current improvement: added `code.index`, `code.symbols`, `code.definition`, `code.references`, `code.diagnostics`, and `code.map` using the existing audited tool executor and normalized results.
- Why it matters: agents can use code intelligence through the same permission, audit, and event pipeline as filesystem/search tools.
- Exact files: `backend/app/tools/codeintel.py`, `backend/app/tools/registry.py`, `backend/app/permissions/policy.py`, `backend/app/agents/registry.py`.
- Exact recommended next fix: add bounded code snippets around definitions only through existing `read.file` permission policy, not directly through code-intel endpoints.
- Risk if ignored: symbols are discoverable, but agents may need an extra tool step to inspect implementation context.

## Context builder

- Current improvement: context includes compact code map data, relevant symbols, and recent error diagnostics within the existing character budget.
- Why it matters: coding agents get useful repository coordinates without unbounded code injection.
- Exact files: `backend/app/runtime/context_builder.py`, `backend/tests/test_codeintel.py`.
- Exact recommended next fix: tune relevance with query extraction and memory/embedding retrieval once embeddings are explicitly enabled.
- Risk if ignored: context remains safe but relevance is heuristic.

## Frontend

- Current improvement: added a `Code` dashboard section for index action/status, LSP fallback status, language counts, metrics, symbol search, diagnostics, and top files.
- Why it matters: users can verify what the runtime has indexed and whether code intelligence is degraded.
- Exact files: `frontend/src/api/client.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles/app.css`.
- Exact recommended next fix: add per-file drill-down with links to existing read/search tool outputs rather than direct raw source exposure.
- Risk if ignored: visibility is enough for MVP, but debugging large indexes is still shallow.

## Smoke validation

- Current improvement: added `scripts/codeintel-smoke.sh` to validate backend health, code indexing, code map, symbols, diagnostics, and outside-workspace rejection.
- Why it matters: live validation can prove the HTTP path and workspace boundary behavior.
- Exact files: `scripts/codeintel-smoke.sh`.
- Exact recommended next fix: rebuild/restart the backend so `GET /health/codeintel` is available, then rerun `scripts/codeintel-smoke.sh`; the current shell hit a stale backend that returned 404 for the new route.
- Risk if ignored: unit tests pass, but live API/indexing behavior is not proven in this shell.

## Tests

- Current improvement: backend tests increased to 109 passed and 1 skipped, covering language detection, parsing, indexing, diagnostics ingestion, LSP fallback, code map counts, tool execution, context integration, OpenAPI routes, and model mappings.
- Why it matters: the code-intelligence MVP is under regression coverage across storage, tools, API, and context layers.
- Exact files: `backend/tests/test_codeintel.py`, `backend/tests/test_db_models.py`, `backend/tests/test_migrations_postgres.py`.
- Exact recommended next fix: add real Postgres migration CI and a Docker-backed codeintel smoke job.
- Risk if ignored: fake-session tests cover behavior, but DB query-plan/index behavior needs real infrastructure validation.

# MCP + Plugin System Parity Batch 1 Implementation Result

## Database

- Current improvement: upgraded MCP/plugin persistence with scoped `mcp_servers`, `mcp_tools`, `plugins`, and `plugin_tools` mappings and migration.
- Why it matters: external capabilities are now explicit, disabled by default, and auditable instead of implicit process memory.
- Exact files: `backend/app/db/models.py`, `backend/app/db/migrations/versions/202606050007_mcp_plugins.py`.
- Exact recommended next fix: add real Postgres constraint checks for external tool uniqueness and scoped plugin/server listing.
- Risk if ignored: unit tests prove mappings, but cross-tenant uniqueness and index behavior need live DB coverage.

## MCP

- Current improvement: added DB-backed server lifecycle, connect failure persistence, redacted env serialization, degraded MCP SDK health, and wrapper tools that normalize results through `ToolResult`.
- Why it matters: MCP can be configured and audited without pretending real protocol execution exists before it is wired.
- Exact files: `backend/app/mcp/client.py`, `backend/app/mcp/service.py`, `backend/app/mcp/tools.py`, `backend/app/api/routes_mcp.py`.
- Exact recommended next fix: wire a real Python MCP SDK transport for stdio/http/sse with timeouts, cancellation, and protocol-level tool discovery tests.
- Risk if ignored: MCP remains a safe metadata/control-plane foundation but cannot yet call real servers.

## Plugins

- Current improvement: added validated manifest loading, disabled-by-default plugin tool rows, explicit enablement, and manifest-only safe `echo` execution for smoke validation.
- Why it matters: plugin state can be managed without importing arbitrary code or bypassing permissions.
- Exact files: `backend/app/plugins/manifest.py`, `backend/app/plugins/service.py`, `backend/app/plugins/tools.py`, `backend/app/api/routes_plugins.py`.
- Exact recommended next fix: design a sandbox/process boundary before enabling arbitrary Python plugin execution.
- Risk if ignored: plugin support remains intentionally limited to manifest metadata and safe sample execution.

## Hooks

- Current improvement: added internal hook registry and tool execution before/after hook points.
- Why it matters: future plugins can observe runtime behavior without mutating core flows by default.
- Exact files: `backend/app/plugins/hooks.py`, `backend/app/runtime/tool_executor.py`, `backend/tests/test_mcp_plugins.py`.
- Exact recommended next fix: add blocking-hook policy, hook execution metrics, and multi-process hook synchronization once real plugin execution exists.
- Risk if ignored: hooks work for in-process internal extensions but are not a distributed plugin runtime yet.

## Frontend

- Current improvement: added an `Extensions` dashboard section for MCP/plugin health, servers, tools, trusted state, and enabled state.
- Why it matters: operators can see degraded/disabled external capability status without digging into raw API responses.
- Exact files: `frontend/src/api/client.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles/app.css`.
- Exact recommended next fix: add guarded enable/disable controls with confirmation copy and permission/risk preview.
- Risk if ignored: visibility exists, but operational control remains API/smoke-script driven.

## Smoke validation

- Current improvement: added `scripts/mcp-plugin-smoke.sh`.
- Why it matters: live runtime can prove disabled-by-default behavior, invalid MCP failure persistence, redacted env, and explicit plugin tool exposure.
- Exact files: `scripts/mcp-plugin-smoke.sh`.
- Exact recommended next fix: run smoke in CI after migration against Docker backend and Postgres; add a real MCP fixture server once protocol support lands.
- Risk if ignored: unit tests pass, but live endpoint/migration drift could still hide until manual validation.

# Real MCP Transport Batch 1 Implementation Result

## MCP SDK and stdio

- Current improvement: added official `mcp>=1.27.2` dependency and replaced the MCP degraded stub with real stdio transport using `ClientSession`, `StdioServerParameters`, and `stdio_client`.
- Why it matters: MCP servers can now be connected, discovered, and called through a real protocol path instead of metadata-only scaffolding.
- Exact files: `pyproject.toml`, `backend/app/mcp/client.py`.
- Exact recommended next fix: add persistent session pooling only after worker/process lifecycle ownership is designed; short-lived sessions are safer for this batch.
- Risk if ignored: repeated calls pay process startup cost, but this avoids leaked subprocesses and premature distributed connection state.

## MCP security controls

- Current improvement: stdio commands are policy-gated, cwd is workspace-checked for untrusted servers, subprocess env is minimized, redacted env values are not passed, stderr is redacted, and large responses are truncated.
- Why it matters: external MCP servers are process boundaries and must not inherit backend secrets or silently escape the workspace.
- Exact files: `backend/app/core/config.py`, `backend/app/mcp/client.py`, `backend/app/db/models.py`, `backend/app/db/migrations/versions/202606050008_real_mcp_stdio.py`.
- Exact recommended next fix: encrypt sensitive MCP env values instead of storing redacted placeholders, then add explicit per-server secret injection rules.
- Risk if ignored: current safe behavior may prevent secret-backed MCP servers from working until encrypted secret storage exists.

## MCP tool lifecycle

- Current improvement: discovered tools are disabled by default, explicit MCP tool enable/disable APIs were added, and enabled tools sync into the native registry as `mcp.<server>.<tool>`.
- Why it matters: MCP tools cannot appear as executable capabilities merely because a trusted server exposed them.
- Exact files: `backend/app/mcp/service.py`, `backend/app/api/routes_mcp.py`, `backend/app/mcp/registry.py`.
- Exact recommended next fix: add UI controls with confirmation/risk preview for enabling MCP servers and tools.
- Risk if ignored: operators can manage MCP through API/smoke scripts, but dashboard control is still incomplete.

## MCP testing and smoke

- Current improvement: added a safe SDK-backed fake MCP stdio server and tests for connect/discovery/call, disabled-by-default rows, registry sync, permission flow, command/cwd guards, and env redaction.
- Why it matters: the transport path is proven against the actual SDK instead of mocked protocol responses.
- Exact files: `backend/tests/fixtures/fake_mcp_server.py`, `backend/tests/test_real_mcp_transport.py`, `scripts/real-mcp-smoke.sh`.
- Exact recommended next fix: run `scripts/real-mcp-smoke.sh` in Docker CI with `AP_ENABLE_TEST_ENDPOINTS=true` for the guarded permission-flow check.
- Risk if ignored: local unit tests prove stdio behavior, but deployment drift in Docker image dependencies or route availability could go unnoticed.

## Remaining MCP polish

- Current problem: HTTP/SSE MCP transport is still degraded and not protocol-wired.
- Why it matters: many MCP servers are remote HTTP/SSE rather than local stdio processes.
- Exact files: `backend/app/mcp/client.py`, `backend/app/api/routes_mcp.py`.
- Exact recommended fix: implement SDK-supported streamable HTTP/SSE clients with authentication, timeout, reconnect, and health semantics.
- Risk if ignored: real MCP support is limited to local stdio servers.

## LSP lifecycle follow-through

- Current improvement: real stdio JSON-RPC LSP lifecycle is now implemented with initialize/shutdown, `didOpen`, document symbols, definitions, references, diagnostics, timeout handling, and bounded response parsing.
- Why it matters: code intelligence can now use a real language server when configured instead of only a placeholder adapter.
- Exact files: `backend/app/codeintel/lsp_client.py`, `backend/app/codeintel/lsp_service.py`, `backend/app/api/routes_codeintel.py`, `backend/app/tools/codeintel.py`.
- Exact recommended next fix: add pooled/per-workspace LSP supervision only after process ownership and cleanup semantics are designed.
- Risk if ignored: the current one-process-at-a-time model is safe and honest, but repeated process startup can add latency for frequent file-based LSP requests.

## Static fallback honesty

- Current improvement: `/health/codeintel` now reports `real_lsp`, `static_fallback`, or `failed` and keeps the indexed database fallback active after command, startup, request, or runtime failures. Real LSP Batch 1 added `LspResult` carrying `items`, `source`, `lsp_status`, `fallback_reason`, and a full `lsp` snapshot; every `/code/...` route and every `code.*` tool result now exposes those fields so consumers can never mistake a fallback for a real-LSP result. `LspService.status()` exposes both `started_at` and `started` aliases.
- Why it matters: operators and tool callers can tell whether semantics are truly coming from a live language server or from the static index.
- Exact files: `backend/app/codeintel/lsp_service.py`, `backend/app/api/routes_codeintel.py`, `backend/app/tools/codeintel.py`, `backend/tests/test_codeintel.py`.
- Exact recommended next fix: add frontend wording that distinguishes semantic LSP results from indexed fallback results in the Code panel.
- Risk if ignored: the backend is honest, but the UI may still leave users guessing which path answered a given request.

## Windows host-side Redis behavior

- Current improvement: host-side unit tests no longer fail when `.env` points Redis at the Docker hostname `redis`; the runtime now degrades to in-process event and queue fallback outside Docker.
- Why it matters: plain `pytest backend/tests` is now viable on Windows and other host environments without special Redis overrides.
- Exact files: `backend/app/runtime/event_bus.py`, `backend/app/queue/jobs.py`, `backend/app/queue/redis_client.py`, `backend/tests/test_event_bus.py`, `backend/tests/test_queue_jobs.py`.
- Exact recommended next fix: add structured logging/metrics for Redis fallback activation so developers can distinguish an intentional host-test fallback from an unexpected runtime outage.
- Risk if ignored: behavior is correct, but fallback activation will remain mostly implicit unless someone checks health responses or code paths directly.

## LSP smoke coverage

- Current improvement: `scripts/lsp-smoke.sh` and `scripts/lsp-smoke.ps1` now accept `--real` / `-Real`; default mode prints `REAL_LSP=disabled_static_fallback`; real mode prints `REAL_LSP=passed` only after `python -c "import pylsp"` succeeds AND at least one `/code/symbols` (or `/code/definition` / `/code/diagnostics`) response body carries `source: real_lsp`. `--skip-real-if-missing` / `-SkipRealIfMissing` prints `REAL_LSP=skipped_pylsp_missing` and exits 0 when pylsp is absent. The smoke never fakes a pass.
- Why it matters: deployment validation has a dedicated code path for real-LSP lifecycle checks and is provably honest about whether real LSP actually handled a request.
- Exact files: `scripts/lsp-smoke.sh`, `scripts/lsp-smoke.ps1`, `scripts/codeintel-smoke.sh`, `pyproject.toml` (`[project.optional-dependencies] codeintel`).
- Exact recommended next fix: get the `CI` workflow green for the commits being used as release evidence, then use `scripts/mark-ci-validated.ps1` to update docs only after the verifier proves success. After that, expand beyond Python to TypeScript/JS LSP and broader language-server coverage.
- Risk if ignored: the Python `pylsp` path is locally validated and the workflow exists, but the release docs can drift away from GitHub-hosted reality if the verifier is not used and the failing CI workflow remains unresolved.

## Queue and worker dashboard

- Current improvement: added `worker_heartbeats`, queue operator APIs, retry/cancel controls, and a runtime dashboard tab for queue depth, worker heartbeat state, and recent queue jobs.
- Why it matters: operators can now see whether workers are alive, whether jobs are failing or piling up, and can manually retry or cancel safe queue states without dropping into SQL or raw API calls.
- Exact files: `backend/app/queue/worker.py`, `backend/app/queue/worker_heartbeats.py`, `backend/app/api/routes_queue.py`, `frontend/src/api/client.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/EventStream.tsx`.
- Exact recommended next fix: add queue/worker websocket fanout or SSE updates so the runtime tab is push-driven instead of polling every few seconds.
- Risk if ignored: visibility is much better, but rapid queue churn can still appear stale between polling intervals.

## Queue worker smoke

- Current improvement: added `scripts/queue-worker-smoke.sh`.
- Why it matters: the runtime can now prove the new queue observability endpoints and manual retry/cancel controls against a live Postgres-backed backend instead of only unit tests.
- Exact files: `scripts/queue-worker-smoke.sh`, `.env.example`.
- Exact recommended next fix: run the smoke in Docker CI after migrations with the backend worker enabled so heartbeat payloads are always exercised in addition to API row mutations.

## File diff / review / undo (Batch 1)

- Current improvement: `FileChange` capture, list, detail, and revert endpoints are wired through `ToolExecutor`, `write.file`/`edit.file`/`patch.apply` emit `before_content`/`after_content`/`sizes` in `ToolResult.metadata`, secret filenames are redacted, content and diff are truncated to configured byte caps, and the Dashboard exposes a **File Changes** tab with revert controls. `scripts/file-change-smoke.ps1` and `.sh` validate route registration and 200/404 round-trips.
- Why it matters: every approved mutation tool now leaves a durable, auditable, revertible trail with secret redaction; users can review and undo risky changes from the UI.
- Exact files: `backend/app/core/config.py`, `backend/app/db/models.py`, `backend/app/db/migrations/versions/202606070001_file_changes.py`, `backend/app/core/events.py`, `backend/app/file_changes/file_change_service.py`, `backend/app/runtime/tool_executor.py`, `backend/app/tools/write.py`, `backend/app/tools/edit.py`, `backend/app/api/routes_file_changes.py`, `backend/app/main.py`, `backend/app/cli/{api_client,render,main}.py`, `backend/tests/test_file_changes.py`, `frontend/src/api/client.ts`, `frontend/src/components/FileChangesPanel.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles/app.css`, `scripts/file-change-smoke.{ps1,sh}`, `scripts/validate-local.ps1`.
- Exact recommended next fix:
  1. Revert route currently returns HTTP 500 (via `FileChangeError`) for hash mismatch when `force` is false; downgrade to 409 to match the documented contract.
  2. Revert still bypasses the permission/approval flow; mirror the `PermissionRequest` lifecycle so destructive reverts cannot be triggered unattended.
  3. Add a round-trip smoke that runs a real `write.file` against a live backend, polls `/file-changes`, calls `POST /file-changes/{id}/revert`, and asserts the on-disk content is restored byte-for-byte. The shipped smoke only validates endpoint registration.
  4. Frontend File Changes panel: add batch select, filter by tool_name/tool_call, and an "approval required" gate that respects the existing permission profile.
  5. Consider Git/VCS fallback (`git show HEAD:<path>`) when `before_content` is missing or out of date.
- Risk if ignored: local development has a deterministic smoke path, but deployment drift in the queue endpoints or worker heartbeat lifecycle could still hide until manual verification.
