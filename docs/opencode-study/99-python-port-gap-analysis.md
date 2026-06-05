# Python Port Gap Analysis Against OpenCode

OpenCode commit analyzed: `f6197cefe1745eef29ea6afae26be5a56c7a79ee`

This report compares the current Python local-first agent platform against the cloned OpenCode source. It is an architecture and behavior audit only. No OpenCode branding, logo, package identity, or affiliation is reused, and no TypeScript implementation is copied.

## Summary

- Subsystems analyzed: 60
- EXISTS_GOOD: 0
- EXISTS_NEEDS_POLISH: 15
- PARTIAL: 39
- MISSING: 4
- WRONG_DIRECTION: 0
- NOT_APPLICABLE: 2
- Priority counts: P0=25, P1=24, P2=9, P3=2

## Executive Assessment

- The Python project is production-shaped: it has FastAPI, async SQLAlchemy, Postgres/pgvector, Redis, Qdrant, Neo4j, MinIO, ClickHouse, React/Vite, Docker Compose, native agents, typed tools, permissions, persisted events, and Ollama integration.
- It is not yet production-ready in the OpenCode sense: the agent loop is synchronous and not resumable, permission approval does not continue waiting tool calls, context building is transcript-only, mutation tools lack strong safety controls, and auth/authorization is not implemented.
- Several infrastructure services exist as boundaries but are not wired into runtime behavior yet: memory, graph, ClickHouse analytics, plugins, MCP, artifacts, and queue workers.
- The next implementation phase should focus on P0 runtime safety and correctness before adding more UI or integration surface area.

## Top P0 Gaps

- **Configuration system** (PARTIAL, 55%): Add environment mode validation and a database-backed settings overlay for permission/model defaults. Next file: `backend/app/core/config.py`. Test: Add backend/tests/test_config.py proving production mode rejects default secrets and loads workspace-specific permission defaults.
- **Session model** (PARTIAL, 65%): Add session lineage/lifecycle fields, enum constraints, and tenant-scoped detail loading. Next file: `backend/app/db/models.py`. Test: Extend backend/tests/test_sessions.py to prove tenant-isolated detail and persisted model/cost/status transitions.
- **Message model** (PARTIAL, 55%): Introduce Pydantic message-part schemas for assistant, tool, permission, and artifact parts. Next file: `backend/app/runtime/message_service.py`. Test: Add backend/tests/test_messages.py proving typed parts round-trip and invalid payloads are rejected.
- **Agent run model** (PARTIAL, 60%): Persist run state transitions and add a resume path invoked by approval or worker scheduling. Next file: `backend/app/runtime/agent_runner.py`. Test: Add backend/tests/test_agent_run_resume.py proving a waiting_permission run continues after approve.
- **Tool call model** (PARTIAL, 65%): Add FK constraints, normalized status enums, and resume metadata for waiting tool calls. Next file: `backend/app/db/models.py`. Test: Extend backend/tests/test_tool_call_persistence.py proving permission_request_id references a row and approved calls complete.
- **Event system** (PARTIAL, 55%): Add typed event schemas and Redis-backed pub/sub while keeping SystemEvent as durable store. Next file: `backend/app/runtime/event_bus.py`. Test: Add backend/tests/test_event_bus.py proving event payload validation and replay after reconnect.
- **WebSocket/realtime events** (PARTIAL, 60%): Create typed event store with reconnect/replay and backend cursor replay support. Next file: `frontend/src/stores/eventStore.ts`. Test: Add frontend event reducer test and backend /sessions/{id}/events replay ordering test.
- **Agent prompts/system instructions** (PARTIAL, 40%): Build a prompt/context composer with role prompt, guardrails, tool examples, workspace summary, and compacted history. Next file: `backend/app/runtime/context_builder.py`. Test: Add backend/tests/test_context_builder.py proving prompts contain role, allowed tools, protocol examples, and max-step guardrails.
- **Agent runtime loop** (PARTIAL, 45%): Refactor into a resumable state machine and queue-backed worker while preserving strict JSON for Ollama tool mode. Next file: `backend/app/runtime/agent_runner.py`. Test: Add backend/tests/test_agent_runtime_state_machine.py covering final, tool, permission-wait/resume, max-step, and invalid JSON paths.
- **Agent context building** (PARTIAL, 30%): Create context builder selecting recent messages, summaries, tool results, workspace metadata, and memory snippets under a budget. Next file: `backend/app/runtime/context_builder.py`. Test: Add backend/tests/test_context_builder.py proving long sessions are windowed and summaries/tool outputs are deterministic.

## Subsystem Analysis

## Subsystem 1: Project/workspace structure

### OpenCode Reference

Files inspected:
- `external/opencode-source/package.json`
- `external/opencode-source/pnpm-workspace.yaml`
- `external/opencode-source/packages/opencode/src/project/project.ts`
- `external/opencode-source/packages/core/src/project/sql.ts`
- Responsibility: OpenCode has a monorepo split into app, server, core, llm, plugin, and opencode packages with project/workspace identity resolved before session, tool, and permission work.
- Important types/classes/functions: `ProjectV2`, `WorkspaceV2`, `ProjectTable`, `SessionTable`
- Runtime flow: OpenCode has a monorepo split into app, server, core, llm, plugin, and opencode packages with project/workspace identity resolved before session, tool, and permission work.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `pyproject.toml`
- `backend/app/db/models.py`
- `backend/app/runtime/tenant.py`
- `frontend/src/pages/Dashboard.tsx`
- Current status: PARTIAL
- OpenCode has what: OpenCode has a monorepo split into app, server, core, llm, plugin, and opencode packages with project/workspace identity resolved before session, tool, and permission work.
- Our Python platform has what: The Python repo has backend, frontend, Docker infrastructure, and multi-tenant Organization, Project, Workspace, and Session tables with bootstrap tenant creation.
- Current behavior: The Python repo has backend, frontend, Docker infrastructure, and multi-tenant Organization, Project, Workspace, and Session tables with bootstrap tenant creation.
- What is missing:
  - No explicit project/workspace switching API
  - No workspace location resolver comparable to OpenCode location middleware
  - No generated client boundary between backend and frontend packages
- What is weak:
  - Bootstrap tenant still behaves like a default local user
  - Frontend does not expose organization/project/workspace selection
- Production risk: Runs can target the wrong workspace root once multiple workspaces exist.
- Exact file to implement or polish next: `backend/app/api/routes_workspaces.py`
- Recommended action: Add project/workspace list/select routes and require selected workspace context on session creation.
- Test that proves it works: Add backend/tests/test_workspaces.py proving session creation uses the requested workspace root and rejects cross-organization IDs.

### Gap Status

- Parity level: 65%
- Priority: P1
- Effort: M
- Owner area: backend

## Subsystem 2: Configuration system

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/config/config.ts`
- `external/opencode-source/packages/opencode/src/config/agent.ts`
- `external/opencode-source/packages/opencode/src/config/plugin.ts`
- `external/opencode-source/packages/opencode/src/config/paths.ts`
- `external/opencode-source/packages/opencode/src/config/parse.ts`
- Responsibility: OpenCode has layered config discovery, path resolution, agent/plugin/permission config parsing, env integration, and dependency waiting.
- Important types/classes/functions: `Config.Service`, `ConfigV1.Info`, `fromConfig`
- Runtime flow: OpenCode has layered config discovery, path resolution, agent/plugin/permission config parsing, env integration, and dependency waiting.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/core/config.py`
- `.env.example`
- `docker-compose.yml`
- Current status: PARTIAL
- OpenCode has what: OpenCode has layered config discovery, path resolution, agent/plugin/permission config parsing, env integration, and dependency waiting.
- Our Python platform has what: Python uses Pydantic Settings with AP_ env prefix, Docker env wiring, and defaults for infrastructure, Ollama, tenant bootstrap, and workspace root.
- Current behavior: Python uses Pydantic Settings with AP_ env prefix, Docker env wiring, and defaults for infrastructure, Ollama, tenant bootstrap, and workspace root.
- What is missing:
  - No persisted or file-based agent/tool/permission config
  - No production validation for default secrets
  - No per-organization or per-workspace overrides
- What is weak:
  - Development defaults include credentials and broad local assumptions
  - Settings are cached until restart
- Production risk: Permission and model behavior cannot be safely tuned per project without auditable scoped config.
- Exact file to implement or polish next: `backend/app/core/config.py`
- Recommended action: Add environment mode validation and a database-backed settings overlay for permission/model defaults.
- Test that proves it works: Add backend/tests/test_config.py proving production mode rejects default secrets and loads workspace-specific permission defaults.

### Gap Status

- Parity level: 55%
- Priority: P0
- Effort: M
- Owner area: backend

## Subsystem 3: Server boot lifecycle

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/server/server.ts`
- `external/opencode-source/packages/opencode/src/server/global-lifecycle.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/serve.ts`
- Responsibility: OpenCode has server creation with lifecycle hooks, route mounting, UI serving, auth/CORS setup, and CLI serve orchestration.
- Important types/classes/functions: `Server.listen`, `globalLifecycle`, `serve command`
- Runtime flow: OpenCode has server creation with lifecycle hooks, route mounting, UI serving, auth/CORS setup, and CLI serve orchestration.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/main.py`
- `backend/app/cli.py`
- `Dockerfile.backend`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode has server creation with lifecycle hooks, route mounting, UI serving, auth/CORS setup, and CLI serve orchestration.
- Our Python platform has what: Python has FastAPI app factory, lifespan logging setup, CORS middleware, explicit router includes, and Typer serve/migrate commands.
- Current behavior: Python has FastAPI app factory, lifespan logging setup, CORS middleware, explicit router includes, and Typer serve/migrate commands.
- What is missing:
  - No startup dependency readiness gate
  - No graceful run cancellation or worker lifecycle
  - No startup validation that migrations are applied
- What is weak:
  - Lifespan configures logging only
  - CLI migrate shells out without structured errors
- Production risk: Containers can report healthy while runtime dependencies are degraded.
- Exact file to implement or polish next: `backend/app/main.py`
- Recommended action: Add startup checks for migrations/dependencies and shutdown hooks for background tasks.
- Test that proves it works: Add backend/tests/test_startup.py using TestClient lifespan to prove failed critical dependencies produce explicit degraded state.

### Gap Status

- Parity level: 70%
- Priority: P1
- Effort: M
- Owner area: backend

## Subsystem 4: API route structure

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/server/src/api.ts`
- `external/opencode-source/packages/server/src/groups/v2/session.ts`
- `external/opencode-source/packages/server/src/groups/v2/message.ts`
- `external/opencode-source/packages/server/src/groups/v2/permission.ts`
- `external/opencode-source/packages/server/src/groups/v2/model.ts`
- Responsibility: OpenCode has typed v2 route groups for sessions, messages, models, providers, permissions, fs, commands, skills, questions, events, and health.
- Important types/classes/functions: `V2Api`, `SessionGroup`, `MessageGroup`, `PermissionGroup`
- Runtime flow: OpenCode has typed v2 route groups for sessions, messages, models, providers, permissions, fs, commands, skills, questions, events, and health.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/main.py`
- `backend/app/api/routes_sessions.py`
- `backend/app/api/routes_messages.py`
- `backend/app/api/routes_permissions.py`
- `backend/app/api/routes_models.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has typed v2 route groups for sessions, messages, models, providers, permissions, fs, commands, skills, questions, events, and health.
- Our Python platform has what: Python has hand-written FastAPI routers for health, models, agents, tools, sessions, messages, permissions, artifacts, system events, and WebSocket.
- Current behavior: Python has hand-written FastAPI routers for health, models, agents, tools, sessions, messages, permissions, artifacts, system events, and WebSocket.
- What is missing:
  - No versioned /api/v1 surface
  - No provider/workspace/filesystem/command/skill/question reply route parity
  - No cursor pagination
- What is weak:
  - Plain dict responses lack shared envelopes
  - Some detail endpoints do not tenant-filter before returning rows
- Production risk: Frontend and future SDK contracts can drift as routes grow.
- Exact file to implement or polish next: `backend/app/api/__init__.py`
- Recommended action: Introduce versioned routers and shared response/error schemas while preserving current aliases.
- Test that proves it works: Add backend/tests/test_api_contract.py validating route envelopes, tenant filtering, and OpenAPI paths.

### Gap Status

- Parity level: 60%
- Priority: P1
- Effort: M
- Owner area: backend

## Subsystem 5: OpenAPI/schema generation

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/server/src/api.ts`
- `external/opencode-source/packages/server/src/groups/v2/session.ts`
- `external/opencode-source/packages/server/src/middleware/schema-error.ts`
- `external/opencode-source/packages/server/src/routes.ts`
- Responsibility: OpenCode route schemas are the API contract and feed SDK/client generation with normalized schema errors.
- Important types/classes/functions: `HttpApi`, `OpenApi.annotations`, `SchemaErrorMiddleware`
- Runtime flow: OpenCode route schemas are the API contract and feed SDK/client generation with normalized schema errors.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/main.py`
- `frontend/src/api/client.ts`
- Current status: PARTIAL
- OpenCode has what: OpenCode route schemas are the API contract and feed SDK/client generation with normalized schema errors.
- Our Python platform has what: FastAPI publishes OpenAPI automatically, but frontend types are manually maintained in client.ts.
- Current behavior: FastAPI publishes OpenAPI automatically, but frontend types are manually maintained in client.ts.
- What is missing:
  - No generated TypeScript client
  - No schema lint check in CI or smoke tests
  - No shared error schema across every route
- What is weak:
  - Manual frontend types can silently drift
  - OpenAPI descriptions are sparse
- Production risk: A backend change can break the UI without compile-time feedback.
- Exact file to implement or polish next: `frontend/src/api/client.ts`
- Recommended action: Add OpenAPI generation and replace manual wire types with generated or schema-checked types.
- Test that proves it works: Add scripts/check-openapi.sh and frontend build validation for generated types.

### Gap Status

- Parity level: 45%
- Priority: P1
- Effort: M
- Owner area: backend/frontend

## Subsystem 6: Session model

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/session.ts`
- `external/opencode-source/packages/opencode/src/session/schema.ts`
- `external/opencode-source/packages/core/src/session/sql.ts`
- Responsibility: OpenCode sessions include slug, project/workspace, directory/path, parent/forking, model, cost, tokens, share, summaries, revert, permissions, and timestamps.
- Important types/classes/functions: `Session.Info`, `SessionTable`, `SessionID`, `fromRow`, `toRow`
- Runtime flow: OpenCode sessions include slug, project/workspace, directory/path, parent/forking, model, cost, tokens, share, summaries, revert, permissions, and timestamps.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/db/models.py`
- `backend/app/runtime/session_service.py`
- `backend/tests/test_sessions.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode sessions include slug, project/workspace, directory/path, parent/forking, model, cost, tokens, share, summaries, revert, permissions, and timestamps.
- Our Python platform has what: Python Session has organization/project/workspace/creator, title, agent, model provider/name, status, and metadata_json.
- Current behavior: Python Session has organization/project/workspace/creator, title, agent, model provider/name, status, and metadata_json.
- What is missing:
  - No parent/fork fields
  - No token/cost summary fields
  - No archive/share/revert lifecycle
  - No explicit directory/path field
- What is weak:
  - Session detail does not tenant-check the requested session
  - Status values are unconstrained strings
- Production risk: Session lineage, accounting, and tenant safety are incomplete.
- Exact file to implement or polish next: `backend/app/db/models.py`
- Recommended action: Add session lineage/lifecycle fields, enum constraints, and tenant-scoped detail loading.
- Test that proves it works: Extend backend/tests/test_sessions.py to prove tenant-isolated detail and persisted model/cost/status transitions.

### Gap Status

- Parity level: 65%
- Priority: P0
- Effort: M
- Owner area: database/backend

## Subsystem 7: Message model

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/message.ts`
- `external/opencode-source/packages/opencode/src/session/message-v2.ts`
- `external/opencode-source/packages/opencode/src/session/schema.ts`
- `external/opencode-source/packages/core/src/session/message.ts`
- Responsibility: OpenCode has typed message/part models for text, tool, file, reasoning, error, and assistant step events.
- Important types/classes/functions: `SessionV1.Message`, `SessionMessage.Message`, `PartTable`, `MessageV2`
- Runtime flow: OpenCode has typed message/part models for text, tool, file, reasoning, error, and assistant step events.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/db/models.py`
- `backend/app/runtime/message_service.py`
- `backend/app/runtime/session_service.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has typed message/part models for text, tool, file, reasoning, error, and assistant step events.
- Our Python platform has what: Python stores role/content messages with JSON parts and metadata plus helpers for user, assistant, and tool result messages.
- Current behavior: Python stores role/content messages with JSON parts and metadata plus helpers for user, assistant, and tool result messages.
- What is missing:
  - No typed message part tables
  - No streaming reasoning/tool part updates
  - No attachments/file references
  - No pagination/windowing
- What is weak:
  - parts is unvalidated JSONB
  - Tool calls are separate and not rich message parts
- Production risk: The UI cannot render precise execution timelines or artifacts without ad hoc metadata parsing.
- Exact file to implement or polish next: `backend/app/runtime/message_service.py`
- Recommended action: Introduce Pydantic message-part schemas for assistant, tool, permission, and artifact parts.
- Test that proves it works: Add backend/tests/test_messages.py proving typed parts round-trip and invalid payloads are rejected.

### Gap Status

- Parity level: 55%
- Priority: P0
- Effort: M
- Owner area: database/backend

## Subsystem 8: Agent run model

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/opencode/src/session/status.ts`
- `external/opencode-source/packages/core/test/session-runner.test.ts`
- Responsibility: OpenCode processor tracks durable step state, blocked/compaction flags, snapshots, and tool settlement state.
- Important types/classes/functions: `ProcessorContext`, `SessionStatus`, `SessionEvent.Step.Started`
- Runtime flow: OpenCode processor tracks durable step state, blocked/compaction flags, snapshots, and tool settlement state.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/db/models.py`
- `backend/app/runtime/agent_runner.py`
- `backend/app/api/routes_messages.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode processor tracks durable step state, blocked/compaction flags, snapshots, and tool settlement state.
- Our Python platform has what: Python AgentRun records agent, model, status, step_count, error, and timestamps for one synchronous run per message.
- Current behavior: Python AgentRun records agent, model, status, step_count, error, and timestamps for one synchronous run per message.
- What is missing:
  - No durable resumable processor state
  - No cancellation/abort ownership
  - No snapshot/context version
  - No background queue
- What is weak:
  - Runs execute inside HTTP requests
  - waiting_permission has no resume entrypoint
- Production risk: Long or permission-blocked runs can be lost or require manual re-prompting.
- Exact file to implement or polish next: `backend/app/runtime/agent_runner.py`
- Recommended action: Persist run state transitions and add a resume path invoked by approval or worker scheduling.
- Test that proves it works: Add backend/tests/test_agent_run_resume.py proving a waiting_permission run continues after approve.

### Gap Status

- Parity level: 60%
- Priority: P0
- Effort: M
- Owner area: runtime/database

## Subsystem 9: Tool call model

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/opencode/src/tool/tool.ts`
- `external/opencode-source/packages/llm/src/tool-runtime.ts`
- Responsibility: OpenCode tool parts track raw streaming input, validated input, output title/metadata/attachments, error status, and settlement.
- Important types/classes/functions: `ToolCall`, `SessionV1.ToolPart`, `Tool.Def`, `ToolOutput`
- Runtime flow: OpenCode tool parts track raw streaming input, validated input, output title/metadata/attachments, error status, and settlement.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/db/models.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/runtime/loop_guard.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode tool parts track raw streaming input, validated input, output title/metadata/attachments, error status, and settlement.
- Our Python platform has what: Python ToolCall stores input_json, input_hash, output_json, status, error, permission_request_id, and timestamps.
- Current behavior: Python ToolCall stores input_json, input_hash, output_json, status, error, permission_request_id, and timestamps.
- What is missing:
  - No raw streamed input tracking
  - No attachment linkage enforcement
  - No normalized tool output table
  - No retry/correction metadata
- What is weak:
  - permission_request_id is not a foreign key
  - waiting_permission rows can remain stuck
- Production risk: Audit history can show approval while the original tool never executed.
- Exact file to implement or polish next: `backend/app/db/models.py`
- Recommended action: Add FK constraints, normalized status enums, and resume metadata for waiting tool calls.
- Test that proves it works: Extend backend/tests/test_tool_call_persistence.py proving permission_request_id references a row and approved calls complete.

### Gap Status

- Parity level: 65%
- Priority: P0
- Effort: M
- Owner area: runtime/database

## Subsystem 10: Event system

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/server/event.ts`
- `external/opencode-source/packages/opencode/src/event-v2-bridge.ts`
- `external/opencode-source/packages/server/src/groups/v2/event.ts`
- `external/opencode-source/packages/core/src/event/index.ts`
- Responsibility: OpenCode has typed EventV2 definitions, an event bridge, location-scoped subscriptions, and app reducers.
- Important types/classes/functions: `EventV2.define`, `SessionEvent`, `EventGroup`
- Runtime flow: OpenCode has typed EventV2 definitions, an event bridge, location-scoped subscriptions, and app reducers.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/core/events.py`
- `backend/app/runtime/event_bus.py`
- `backend/app/db/models.py`
- `backend/app/api/routes_system_events.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has typed EventV2 definitions, an event bridge, location-scoped subscriptions, and app reducers.
- Our Python platform has what: Python has EventType strings, persisted SystemEvent rows, in-process WebSocket broadcast, and a system events route.
- Current behavior: Python has EventType strings, persisted SystemEvent rows, in-process WebSocket broadcast, and a system events route.
- What is missing:
  - No Pydantic schema per event type
  - No Redis pub/sub cross-process broadcast
  - No replay cursor
  - No location/workspace subscription filter
- What is weak:
  - In-process subscribers do not work across replicas
  - Payloads are untyped JSON
- Production risk: Multi-container deployments will lose live events for sessions handled by another process.
- Exact file to implement or polish next: `backend/app/runtime/event_bus.py`
- Recommended action: Add typed event schemas and Redis-backed pub/sub while keeping SystemEvent as durable store.
- Test that proves it works: Add backend/tests/test_event_bus.py proving event payload validation and replay after reconnect.

### Gap Status

- Parity level: 55%
- Priority: P0
- Effort: M
- Owner area: runtime/backend

## Subsystem 11: WebSocket/realtime events

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/server/src/groups/v2/event.ts`
- `external/opencode-source/packages/server/src/handlers/v2/event.ts`
- `external/opencode-source/packages/app/src/context/server-sync.tsx`
- `external/opencode-source/packages/app/src/context/global-sync/event-reducer.ts`
- Responsibility: OpenCode exposes SSE subscriptions with typed reducers and scoped sync state.
- Important types/classes/functions: `EventGroup.events`, `serverSDK.event.listen`, `event-reducer`
- Runtime flow: OpenCode exposes SSE subscriptions with typed reducers and scoped sync state.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/api/websocket.py`
- `backend/app/runtime/event_bus.py`
- `frontend/src/pages/Dashboard.tsx`
- Current status: PARTIAL
- OpenCode has what: OpenCode exposes SSE subscriptions with typed reducers and scoped sync state.
- Our Python platform has what: Python exposes a session WebSocket and React opens one for the selected session, refetching detail on every event.
- Current behavior: Python exposes a session WebSocket and React opens one for the selected session, refetching detail on every event.
- What is missing:
  - No heartbeat/ping protocol
  - No reconnect replay cursor
  - No global WebSocket route
  - No typed frontend reducer
- What is weak:
  - Receive loop ignores client messages
  - UI refetches full session detail on every event
- Production risk: Users can miss permission prompts or tool updates during network blips.
- Exact file to implement or polish next: `frontend/src/stores/eventStore.ts`
- Recommended action: Create typed event store with reconnect/replay and backend cursor replay support.
- Test that proves it works: Add frontend event reducer test and backend /sessions/{id}/events replay ordering test.

### Gap Status

- Parity level: 60%
- Priority: P0
- Effort: M
- Owner area: backend/frontend

## Subsystem 12: Agent registry

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/agent/agent.ts`
- `external/opencode-source/packages/opencode/src/config/agent.ts`
- `external/opencode-source/packages/server/src/groups/v2/agent.ts`
- Responsibility: OpenCode merges built-in agents with config, model/tool permissions, and subagent restrictions.
- Important types/classes/functions: `Agent.Info`, `Agent.Service`, `subagent-permissions`
- Runtime flow: OpenCode merges built-in agents with config, model/tool permissions, and subagent restrictions.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/agents/base.py`
- `backend/app/agents/registry.py`
- `backend/app/api/routes_agents.py`
- `backend/tests/test_agent_registry.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode merges built-in agents with config, model/tool permissions, and subagent restrictions.
- Our Python platform has what: Python has static build, plan, general, explore, summary, and compaction agents with list/get API.
- Current behavior: Python has static build, plan, general, explore, summary, and compaction agents with list/get API.
- What is missing:
  - No dynamic agent config
  - No per-project overrides
  - No subagent task spawning semantics
- What is weak:
  - Prompts are terse and JSON-protocol focused
  - Allowed tools are fixed at startup
- Production risk: Operators cannot tune agents without code changes.
- Exact file to implement or polish next: `backend/app/agents/registry.py`
- Recommended action: Load validated agent overrides from database while retaining safe built-in defaults.
- Test that proves it works: Extend backend/tests/test_agent_registry.py proving project-specific override changes model/tools safely.

### Gap Status

- Parity level: 70%
- Priority: P1
- Effort: M
- Owner area: backend

## Subsystem 13: Native agents

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/agent/agent.ts`
- `external/opencode-source/packages/opencode/src/agent/prompt/explore.txt`
- `external/opencode-source/packages/opencode/src/agent/prompt/summary.txt`
- `external/opencode-source/packages/opencode/src/agent/prompt/compaction.txt`
- `external/opencode-source/packages/opencode/src/session/prompt/plan.txt`
- Responsibility: OpenCode has built-in role prompts, plan/build transitions, summary/compaction internals, and task/subagent permissions.
- Important types/classes/functions: `build mode`, `plan mode`, `explore prompt`, `summary prompt`, `compaction prompt`
- Runtime flow: OpenCode has built-in role prompts, plan/build transitions, summary/compaction internals, and task/subagent permissions.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/agents/registry.py`
- `backend/app/agents/base.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has built-in role prompts, plan/build transitions, summary/compaction internals, and task/subagent permissions.
- Our Python platform has what: Python has the requested six native agents with ids, metadata, model config, prompts, tools, permission profile, max steps, and hidden flags.
- Current behavior: Python has the requested six native agents with ids, metadata, model config, prompts, tools, permission profile, max steps, and hidden flags.
- What is missing:
  - No role-specific prompt files
  - No agent-to-agent task tool
  - No build/plan switching protocol
  - No summarization/compaction execution path
- What is weak:
  - Prompts are embedded constants
  - general chat still has editing tools
- Production risk: Local chat can request high-authority tools unless permissions catch every path.
- Exact file to implement or polish next: `backend/app/agents/prompts.py`
- Recommended action: Move prompts into versioned modules/files and reduce general chat tool authority by default.
- Test that proves it works: Add backend/tests/test_agent_permissions.py proving general/chat cannot mutate files unless configured.

### Gap Status

- Parity level: 55%
- Priority: P1
- Effort: M
- Owner area: backend

## Subsystem 14: Agent prompts/system instructions

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/prompt/default.txt`
- `external/opencode-source/packages/opencode/src/session/prompt/plan.txt`
- `external/opencode-source/packages/opencode/src/session/prompt/build-switch.txt`
- `external/opencode-source/packages/opencode/src/session/prompt/max-steps.txt`
- `external/opencode-source/packages/opencode/src/agent/prompt/compaction.txt`
- Responsibility: OpenCode composes default, plan/build, provider-specific, max-step, compaction, and summary prompt assets.
- Important types/classes/functions: `session prompt files`, `Agent prompt files`, `Instruction context`
- Runtime flow: OpenCode composes default, plan/build, provider-specific, max-step, compaction, and summary prompt assets.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/agents/registry.py`
- `backend/app/runtime/agent_runner.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode composes default, plan/build, provider-specific, max-step, compaction, and summary prompt assets.
- Our Python platform has what: Python concatenates a strict JSON runtime prompt, short role instructions, and compact tool schemas.
- Current behavior: Python concatenates a strict JSON runtime prompt, short role instructions, and compact tool schemas.
- What is missing:
  - No prompt composition pipeline
  - No provider/model-specific prompt variants
  - No max-step or permission reminder injection
  - No prompt version snapshot on model calls
- What is weak:
  - Local models often ignore strict JSON
  - Tool schema lacks examples
- Production risk: The platform may chat but fail to reliably invoke tools for implementation tasks.
- Exact file to implement or polish next: `backend/app/runtime/context_builder.py`
- Recommended action: Build a prompt/context composer with role prompt, guardrails, tool examples, workspace summary, and compacted history.
- Test that proves it works: Add backend/tests/test_context_builder.py proving prompts contain role, allowed tools, protocol examples, and max-step guardrails.

### Gap Status

- Parity level: 40%
- Priority: P0
- Effort: M
- Owner area: runtime/backend

## Subsystem 15: Agent runtime loop

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/opencode/src/session/llm.ts`
- `external/opencode-source/packages/opencode/src/session/llm/ai-sdk.ts`
- `external/opencode-source/packages/llm/src/tool-runtime.ts`
- Responsibility: OpenCode has a streaming processor with tool settlement, permission blocking, snapshots, compaction, reasoning parts, and LLM events.
- Important types/classes/functions: `SessionProcessor.Handle`, `ProcessorContext`, `LLM.StreamInput`, `LLMEvent`
- Runtime flow: OpenCode has a streaming processor with tool settlement, permission blocking, snapshots, compaction, reasoning parts, and LLM events.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/runtime/agent_runner.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/providers/ollama.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has a streaming processor with tool settlement, permission blocking, snapshots, compaction, reasoning parts, and LLM events.
- Our Python platform has what: Python runs a synchronous bounded loop that calls Ollama, parses JSON final/tool_call, executes tools, and persists messages/runs/model calls.
- Current behavior: Python runs a synchronous bounded loop that calls Ollama, parses JSON final/tool_call, executes tools, and persists messages/runs/model calls.
- What is missing:
  - No streaming token/tool events
  - No resume after permission approval
  - No cancellation
  - No background ownership/locks
  - No compaction trigger
- What is weak:
  - Runs happen inside request/response
  - Context is unbudgeted transcript
  - Tool failure ends run instead of allowing correction
- Production risk: Production users will see blocked HTTP requests and brittle local model tool behavior.
- Exact file to implement or polish next: `backend/app/runtime/agent_runner.py`
- Recommended action: Refactor into a resumable state machine and queue-backed worker while preserving strict JSON for Ollama tool mode.
- Test that proves it works: Add backend/tests/test_agent_runtime_state_machine.py covering final, tool, permission-wait/resume, max-step, and invalid JSON paths.

### Gap Status

- Parity level: 45%
- Priority: P0
- Effort: L
- Owner area: runtime

## Subsystem 16: Agent step limits

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/prompt/max-steps.txt`
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/core/test/session-runner.test.ts`
- Responsibility: OpenCode combines runtime step decisions with prompt guidance that can stop, continue, or compact.
- Important types/classes/functions: `DOOM_LOOP_THRESHOLD`, `Result compact/stop/continue`, `max-steps prompt`
- Runtime flow: OpenCode combines runtime step decisions with prompt guidance that can stop, continue, or compact.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/agents/registry.py`
- `backend/app/runtime/agent_runner.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode combines runtime step decisions with prompt guidance that can stop, continue, or compact.
- Our Python platform has what: Python AgentDefinition has max_steps and AgentRunner loops for range(agent.max_steps).
- Current behavior: Python AgentDefinition has max_steps and AgentRunner loops for range(agent.max_steps).
- What is missing:
  - No model-facing final-step reminder
  - No compaction-before-stop option
  - No per-session step override
- What is weak:
  - Max-step failure is generic
  - No event emitted for each step
- Production risk: Agents can stop abruptly without useful recovery guidance.
- Exact file to implement or polish next: `backend/app/runtime/agent_runner.py`
- Recommended action: Emit step events and inject a final-step reminder before the last model call.
- Test that proves it works: Extend backend/tests/test_agent_loop.py proving max-step stop persists failure and emits an event.

### Gap Status

- Parity level: 70%
- Priority: P1
- Effort: S
- Owner area: runtime

## Subsystem 17: Agent context building

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/instruction.ts`
- `external/opencode-source/packages/opencode/src/session/system.ts`
- `external/opencode-source/packages/core/test/system-context.test.ts`
- `external/opencode-source/packages/core/test/instruction-context.test.ts`
- Responsibility: OpenCode gathers system context and instructions from project, files, config, tools, prompts, and session state.
- Important types/classes/functions: `Instruction service`, `System context registry`, `Session context`
- Runtime flow: OpenCode gathers system context and instructions from project, files, config, tools, prompts, and session state.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/runtime/agent_runner.py`
- `backend/app/runtime/session_service.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode gathers system context and instructions from project, files, config, tools, prompts, and session state.
- Our Python platform has what: Python loads all persisted messages and formats role/content text as transcript.
- Current behavior: Python loads all persisted messages and formats role/content text as transcript.
- What is missing:
  - No dedicated context builder
  - No token budget/windowing
  - No workspace summary
  - No memory retrieval
  - No active file/artifact references
- What is weak:
  - Transcript-only context degrades quickly
  - Tool results are raw JSON text
- Production risk: Long sessions become unreliable and local models lose operational context.
- Exact file to implement or polish next: `backend/app/runtime/context_builder.py`
- Recommended action: Create context builder selecting recent messages, summaries, tool results, workspace metadata, and memory snippets under a budget.
- Test that proves it works: Add backend/tests/test_context_builder.py proving long sessions are windowed and summaries/tool outputs are deterministic.

### Gap Status

- Parity level: 30%
- Priority: P0
- Effort: L
- Owner area: runtime

## Subsystem 18: Compaction/summarization

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/compaction.ts`
- `external/opencode-source/packages/opencode/src/session/summary.ts`
- `external/opencode-source/packages/opencode/src/agent/prompt/summary.txt`
- `external/opencode-source/packages/opencode/src/agent/prompt/compaction.txt`
- Responsibility: OpenCode has summary/compaction services, prompts, compact endpoint behavior, and overflow-triggered compaction.
- Important types/classes/functions: `SessionSummary.Service`, `summary prompt`, `compaction prompt`
- Runtime flow: OpenCode has summary/compaction services, prompts, compact endpoint behavior, and overflow-triggered compaction.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/agents/registry.py`
- `backend/app/runtime/agent_runner.py`
- Current status: MISSING
- OpenCode has what: OpenCode has summary/compaction services, prompts, compact endpoint behavior, and overflow-triggered compaction.
- Our Python platform has what: Python registers hidden summary and compaction agents but no runtime path invokes them.
- Current behavior: Python registers hidden summary and compaction agents but no runtime path invokes them.
- What is missing:
  - No compaction endpoint
  - No summary persistence
  - No overflow detector
  - No compacted context boundary
- What is weak:
  - Hidden agents imply a capability that is unreachable
- Production risk: Long sessions eventually fail or become incoherent.
- Exact file to implement or polish next: `backend/app/runtime/compaction_service.py`
- Recommended action: Implement summary storage and /sessions/{id}/compact without deleting original messages.
- Test that proves it works: Add backend/tests/test_compaction.py proving compact creates summary metadata and later context uses it.

### Gap Status

- Parity level: 10%
- Priority: P1
- Effort: L
- Owner area: runtime/backend

## Subsystem 19: Model provider abstraction

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/provider/provider.ts`
- `external/opencode-source/packages/opencode/src/provider/model-status.ts`
- `external/opencode-source/packages/llm/src/provider.ts`
- `external/opencode-source/packages/llm/src/providers/index.ts`
- Responsibility: OpenCode has provider registry with auth, config, transforms, model discovery/status, and many SDK-backed adapters.
- Important types/classes/functions: `Provider.Info`, `ModelStatus`, `LanguageModelV3`, `ProviderTransform`
- Runtime flow: OpenCode has provider registry with auth, config, transforms, model discovery/status, and many SDK-backed adapters.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/providers/base.py`
- `backend/app/providers/ollama.py`
- `backend/app/providers/router.py`
- `backend/app/db/models.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has provider registry with auth, config, transforms, model discovery/status, and many SDK-backed adapters.
- Our Python platform has what: Python has an Ollama provider implementation and router returning only Ollama.
- Current behavior: Python has an Ollama provider implementation and router returning only Ollama.
- What is missing:
  - No provider interface enforcement in tests
  - No streaming API
  - No embeddings interface
  - No provider status persistence
- What is weak:
  - ModelProvider table is not used by routing
  - Provider errors mostly pass through httpx
- Production risk: Even Ollama-only routing needs capabilities and health state for safe model selection.
- Exact file to implement or polish next: `backend/app/providers/base.py`
- Recommended action: Formalize provider capabilities and persist provider/model health snapshots.
- Test that proves it works: Extend backend/tests/test_ollama_provider.py proving capability metadata and error normalization.

### Gap Status

- Parity level: 40%
- Priority: P1
- Effort: M
- Owner area: backend

## Subsystem 20: Ollama/local model support

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/provider/provider.ts`
- `external/opencode-source/packages/llm/src/providers/openai-compatible.ts`
- `external/opencode-source/packages/server/src/groups/v2/model.ts`
- Responsibility: OpenCode exposes generic provider/model listing and model status through server/provider APIs.
- Important types/classes/functions: `ModelGroup`, `Provider models`, `ModelStatus`
- Runtime flow: OpenCode exposes generic provider/model listing and model status through server/provider APIs.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/providers/ollama.py`
- `backend/app/api/routes_models.py`
- `docker-compose.yml`
- `scripts/pull-ollama-models.sh`
- `frontend/src/pages/Dashboard.tsx`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode exposes generic provider/model listing and model status through server/provider APIs.
- Our Python platform has what: Python lists host Ollama tags, pulls models, generates via /api/generate, and exposes health/models endpoints and a Chat dropdown.
- Current behavior: Python lists host Ollama tags, pulls models, generates via /api/generate, and exposes health/models endpoints and a Chat dropdown.
- What is missing:
  - No model capability detection
  - No streaming generate endpoint
  - No pull progress events
  - No per-model context/token defaults
- What is weak:
  - All models are treated as JSON-capable tool users
  - num_predict default is low for substantive chat
- Production risk: Some Ollama tags will chat but fail tool protocol or truncate responses.
- Exact file to implement or polish next: `backend/app/providers/ollama.py`
- Recommended action: Add model capability metadata and separate plain chat mode from strict tool JSON mode.
- Test that proves it works: Extend backend/tests/test_ollama_provider.py proving list includes host models and generate supports chat/tool modes.

### Gap Status

- Parity level: 75%
- Priority: P1
- Effort: M
- Owner area: backend/frontend

## Subsystem 21: Tool registry

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/registry.ts`
- `external/opencode-source/packages/opencode/src/tool/tool.ts`
- `external/opencode-source/packages/opencode/src/tool/schema.ts`
- `external/opencode-source/packages/plugin/src/tool.ts`
- Responsibility: OpenCode loads built-in, config, plugin, skill, LSP, web, and model/agent-filtered tools.
- Important types/classes/functions: `ToolRegistry.Service`, `Tool.Def`, `ToolDefinition`
- Runtime flow: OpenCode loads built-in, config, plugin, skill, LSP, web, and model/agent-filtered tools.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/registry.py`
- `backend/app/tools/base.py`
- `backend/app/runtime/tool_executor.py`
- `backend/tests/test_tool_registry.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode loads built-in, config, plugin, skill, LSP, web, and model/agent-filtered tools.
- Our Python platform has what: Python has a static registry of nine native BaseTool implementations with Pydantic schemas and permission keys.
- Current behavior: Python has a static registry of nine native BaseTool implementations with Pydantic schemas and permission keys.
- What is missing:
  - No plugin/MCP tool registration
  - No skill/task/LSP/web tools
  - No model-specific filtering
  - No disabled-tool calculation from permission rules
- What is weak:
  - Registry is process-static
  - OpenCode-to-Python tool mapping is not exposed in API docs
- Production risk: Extensibility is blocked until trusted dynamic tool sources are supported.
- Exact file to implement or polish next: `backend/app/tools/registry.py`
- Recommended action: Add reloadable registry providers for plugin/MCP tools while preserving typed Pydantic boundaries.
- Test that proves it works: Extend backend/tests/test_tool_registry.py proving duplicate names are rejected and dynamic tools expose schemas safely.

### Gap Status

- Parity level: 65%
- Priority: P1
- Effort: M
- Owner area: tools/runtime

## Subsystem 22: Tool metadata/schema validation

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/schema.ts`
- `external/opencode-source/packages/opencode/src/tool/json-schema.ts`
- `external/opencode-source/packages/opencode/src/tool/tool.ts`
- Responsibility: OpenCode tools expose parameter schemas, JSON schema conversion, metadata, attachments, and typed output.
- Important types/classes/functions: `Tool.Def`, `jsonSchema`, `parameters`, `ToolOutput`
- Runtime flow: OpenCode tools expose parameter schemas, JSON schema conversion, metadata, attachments, and typed output.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/base.py`
- `backend/app/runtime/tool_executor.py`
- `backend/tests/test_tool_registry.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode tools expose parameter schemas, JSON schema conversion, metadata, attachments, and typed output.
- Our Python platform has what: Python BaseTool exposes model_json_schema for input/output, permission_key, timeout, resource, and async run.
- Current behavior: Python BaseTool exposes model_json_schema for input/output, permission_key, timeout, resource, and async run.
- What is missing:
  - No schema_version field
  - No examples in tool schemas
  - No standardized invalid-tool correction output
- What is weak:
  - Validation failures do not always emit TOOL_CALL_FAILED
  - Output schema is generic for all tools
- Production risk: Local models receive sparse tool guidance and call tools incorrectly.
- Exact file to implement or polish next: `backend/app/tools/base.py`
- Recommended action: Add schema_version/examples and standardize invalid input feedback.
- Test that proves it works: Extend backend/tests/test_tool_registry.py proving every tool has examples, schema_version, and valid JSON schema.

### Gap Status

- Parity level: 75%
- Priority: P1
- Effort: S
- Owner area: tools

## Subsystem 23: File read tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/read.ts`
- `external/opencode-source/packages/core/test/tool-read.test.ts`
- Responsibility: OpenCode read supports file/directory reads, permissions, truncation, and tests.
- Important types/classes/functions: `ReadTool`, `external-directory tool`, `tool-read tests`
- Runtime flow: OpenCode read supports file/directory reads, permissions, truncation, and tests.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/read.py`
- `backend/app/permissions/policy.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode read supports file/directory reads, permissions, truncation, and tests.
- Our Python platform has what: Python ReadFileTool lists directories, reads UTF-8 line windows, previews binary base64, and uses default allow/read policy.
- Current behavior: Python ReadFileTool lists directories, reads UTF-8 line windows, previews binary base64, and uses default allow/read policy.
- What is missing:
  - No secret-file deny/ask rules
  - No symlink escape tests
  - No ignore/gitignore behavior
- What is weak:
  - Binary preview can leak sensitive bytes after approval
  - Directory listing lacks stat metadata
- Production risk: Symlink or secret file paths can expose data unexpectedly.
- Exact file to implement or polish next: `backend/app/tools/read.py`
- Recommended action: Add secret path detection and symlink escape checks before reading.
- Test that proves it works: Add backend/tests/test_read_tool.py proving symlink escape asks/denies and .env-like files require approval.

### Gap Status

- Parity level: 75%
- Priority: P1
- Effort: S
- Owner area: tools

## Subsystem 24: File write tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/write.ts`
- `external/opencode-source/packages/core/test/tool-write.test.ts`
- `external/opencode-source/packages/core/test/file-mutation.test.ts`
- Responsibility: OpenCode write is permission-aware and tested around mutation behavior.
- Important types/classes/functions: `WriteTool`, `file mutation tests`
- Runtime flow: OpenCode write is permission-aware and tested around mutation behavior.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/write.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/permissions/policy.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode write is permission-aware and tested around mutation behavior.
- Our Python platform has what: Python WriteFileTool writes full content and creates parent directories after ASK permission is created.
- Current behavior: Python WriteFileTool writes full content and creates parent directories after ASK permission is created.
- What is missing:
  - No atomic write
  - No snapshot/diff before write
  - No secret-file protection
  - No resume-after-approval execution
- What is weak:
  - Parent directories are created once permission is approved without separate context
  - No file mode preservation
- Production risk: Approved writes can overwrite critical files without diff preview or rollback.
- Exact file to implement or polish next: `backend/app/tools/write.py`
- Recommended action: Add diff preview metadata, atomic write, symlink/secret checks, and approval resume integration.
- Test that proves it works: Add backend/tests/test_write_tool.py proving ask flow, atomic write, and denied secret overwrite.

### Gap Status

- Parity level: 55%
- Priority: P0
- Effort: M
- Owner area: tools/permissions

## Subsystem 25: Edit/patch tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/edit.ts`
- `external/opencode-source/packages/opencode/src/tool/apply_patch.ts`
- `external/opencode-source/packages/opencode/src/patch/index.ts`
- `external/opencode-source/packages/core/test/tool-edit.test.ts`
- `external/opencode-source/packages/core/test/tool-apply-patch.test.ts`
- Responsibility: OpenCode has edit/apply_patch tools backed by patch parsing, mutation tests, and output handling.
- Important types/classes/functions: `EditTool`, `ApplyPatchTool`, `Patch parser`
- Runtime flow: OpenCode has edit/apply_patch tools backed by patch parsing, mutation tests, and output handling.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/edit.py`
- `backend/app/tools/patch.py`
- `backend/app/permissions/policy.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has edit/apply_patch tools backed by patch parsing, mutation tests, and output handling.
- Our Python platform has what: Python edit does string replacement and patch supports simple Begin/End add/update/delete hunks.
- Current behavior: Python edit does string replacement and patch supports simple Begin/End add/update/delete hunks.
- What is missing:
  - No robust unified diff parser
  - No multi-hunk context matching
  - No rollback/snapshot
  - No formatting/conflict output
- What is weak:
  - Patch update can mishandle context
  - Edit only supports exact substring replacement
- Production risk: Patch application can corrupt files or fail on common diffs.
- Exact file to implement or polish next: `backend/app/tools/patch.py`
- Recommended action: Replace simple parser with a tested patch engine and store before/after diff metadata.
- Test that proves it works: Add backend/tests/test_patch_tool.py with add/update/delete, multi-hunk, context mismatch, and rollback cases.

### Gap Status

- Parity level: 45%
- Priority: P0
- Effort: L
- Owner area: tools

## Subsystem 26: Bash/shell tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/shell.ts`
- `external/opencode-source/packages/opencode/src/shell/shell.ts`
- `external/opencode-source/packages/core/test/tool-bash.test.ts`
- Responsibility: OpenCode shell execution is abstracted, permission-integrated, output-truncated, and tested.
- Important types/classes/functions: `ShellTool`, `shell service`, `tool-bash tests`
- Runtime flow: OpenCode shell execution is abstracted, permission-integrated, output-truncated, and tested.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/bash.py`
- `backend/app/permissions/policy.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode shell execution is abstracted, permission-integrated, output-truncated, and tested.
- Our Python platform has what: Python BashRunTool uses asyncio.create_subprocess_shell with workdir, timeout, combined stdout/stderr, and output truncation.
- Current behavior: Python BashRunTool uses asyncio.create_subprocess_shell with workdir, timeout, combined stdout/stderr, and output truncation.
- What is missing:
  - No shell sandbox
  - No command AST/prefix allow rules
  - No environment scrub
  - No interactive process control
  - No exit-code failure policy
- What is weak:
  - Shell expansion is enabled
  - External effects depend heavily on manual approval
- Production risk: Shell execution is the highest-risk tool and currently too broad.
- Exact file to implement or polish next: `backend/app/tools/bash.py`
- Recommended action: Add shell policy with safe parsing, env scrub, cwd enforcement, and explicit exit-code handling.
- Test that proves it works: Add backend/tests/test_bash_tool.py proving destructive deny, external cwd ask, env scrub, and nonzero exit failure.

### Gap Status

- Parity level: 40%
- Priority: P0
- Effort: L
- Owner area: tools/security

## Subsystem 27: Grep/search tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/grep.ts`
- `external/opencode-source/packages/core/test/tool-grep.test.ts`
- Responsibility: OpenCode has ripgrep-backed search with result limits, filesystem utilities, and tests.
- Important types/classes/functions: `GrepTool`, `Ripgrep.Service`
- Runtime flow: OpenCode has ripgrep-backed search with result limits, filesystem utilities, and tests.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/grep.py`
- `backend/tests/test_tool_registry.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode has ripgrep-backed search with result limits, filesystem utilities, and tests.
- Our Python platform has what: Python GrepSearchTool uses rg when present, falls back to Python regex traversal, and truncates to 100 matches.
- Current behavior: Python GrepSearchTool uses rg when present, falls back to Python regex traversal, and truncates to 100 matches.
- What is missing:
  - No gitignore/hidden-file controls
  - No binary skip reporting
  - No structured result schema beyond text output
- What is weak:
  - Fallback traversal can be slow
  - Regex errors are not normalized
- Production risk: Large repositories can make search slow or noisy.
- Exact file to implement or polish next: `backend/app/tools/grep.py`
- Recommended action: Normalize regex errors and add include/exclude/gitignore options.
- Test that proves it works: Add backend/tests/test_grep_tool.py proving rg and fallback paths return identical bounded results.

### Gap Status

- Parity level: 70%
- Priority: P2
- Effort: S
- Owner area: tools

## Subsystem 28: Glob tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/glob.ts`
- `external/opencode-source/packages/core/test/tool-glob.test.ts`
- Responsibility: OpenCode glob is integrated with filesystem utilities and tests for file discovery.
- Important types/classes/functions: `GlobTool`, `Glob.scanSync`
- Runtime flow: OpenCode glob is integrated with filesystem utilities and tests for file discovery.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/glob.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode glob is integrated with filesystem utilities and tests for file discovery.
- Our Python platform has what: Python GlobSearchTool uses pathlib glob under workspace root and returns up to 100 paths sorted by mtime.
- Current behavior: Python GlobSearchTool uses pathlib glob under workspace root and returns up to 100 paths sorted by mtime.
- What is missing:
  - No recursive globstar policy tests
  - No gitignore/hidden handling
  - No explicit external path ask test
- What is weak:
  - pathlib semantics may differ from fast-glob expectations
  - No directory size guard
- Production risk: Models can miss files or scan too much in large workspaces.
- Exact file to implement or polish next: `backend/app/tools/glob.py`
- Recommended action: Define glob semantics and ignore behavior matching platform expectations.
- Test that proves it works: Add backend/tests/test_glob_tool.py proving recursive patterns, hidden files, and result truncation.

### Gap Status

- Parity level: 70%
- Priority: P2
- Effort: S
- Owner area: tools

## Subsystem 29: Todo tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/todo.ts`
- `external/opencode-source/packages/opencode/src/session/todo.ts`
- `external/opencode-source/packages/core/test/tool-todowrite.test.ts`
- `external/opencode-source/packages/core/test/session-todo.test.ts`
- Responsibility: OpenCode has todo.write backed by session todo state and tests for persistence/update behavior.
- Important types/classes/functions: `TodoWriteTool`, `Todo.Service`
- Runtime flow: OpenCode has todo.write backed by session todo state and tests for persistence/update behavior.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/todo.py`
- `backend/app/db/models.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has todo.write backed by session todo state and tests for persistence/update behavior.
- Our Python platform has what: Python TodoWriteTool validates todo items and returns them in tool output metadata.
- Current behavior: Python TodoWriteTool validates todo items and returns them in tool output metadata.
- What is missing:
  - No durable session todo state
  - No API to read current todos
  - No UI todo panel
  - No audit of todo transitions
- What is weak:
  - Tool says update but only returns metadata
  - Todos disappear from prominent UI after scroll
- Production risk: Users cannot trust todo state as a runtime planning artifact.
- Exact file to implement or polish next: `backend/app/runtime/todo_service.py`
- Recommended action: Persist latest todo list per session and expose it in session detail.
- Test that proves it works: Add backend/tests/test_todo_tool.py proving todo.write updates durable session todo state.

### Gap Status

- Parity level: 35%
- Priority: P1
- Effort: M
- Owner area: runtime/tools

## Subsystem 30: Question/human input tool

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/question.ts`
- `external/opencode-source/packages/opencode/src/question/index.ts`
- `external/opencode-source/packages/server/src/groups/v2/question.ts`
- `external/opencode-source/packages/core/test/tool-question.test.ts`
- Responsibility: OpenCode has a question tool and API flow for asking the user and continuing based on answers.
- Important types/classes/functions: `QuestionTool`, `Question.Service`, `QuestionGroup`
- Runtime flow: OpenCode has a question tool and API flow for asking the user and continuing based on answers.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/tools/question.py`
- `frontend/src/pages/Dashboard.tsx`
- Current status: PARTIAL
- OpenCode has what: OpenCode has a question tool and API flow for asking the user and continuing based on answers.
- Our Python platform has what: Python QuestionAskTool validates question prompts and returns metadata saying questions were recorded for UI.
- Current behavior: Python QuestionAskTool validates question prompts and returns metadata saying questions were recorded for UI.
- What is missing:
  - No question_requests table
  - No question.requested event
  - No answer endpoint
  - No run pause/resume on answer
- What is weak:
  - Tool output claims UI recording that does not exist
- Production risk: Agents that ask clarifying questions cannot receive answers through the runtime.
- Exact file to implement or polish next: `backend/app/runtime/question_service.py`
- Recommended action: Implement question lifecycle parallel to permission requests with answer resume.
- Test that proves it works: Add backend/tests/test_question_flow.py proving question.ask pauses and resumes with a user answer.

### Gap Status

- Parity level: 30%
- Priority: P1
- Effort: M
- Owner area: runtime/frontend

## Subsystem 31: Permission engine

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/permission/index.ts`
- `external/opencode-source/packages/opencode/src/permission/evaluate.ts`
- `external/opencode-source/packages/core/test/permission.test.ts`
- Responsibility: OpenCode has wildcard rules, ask/reply lifecycle, once/always/reject replies, saved approvals, and deferred execution gating.
- Important types/classes/functions: `Permission.evaluate`, `Permission.Service.ask`, `Permission.Service.reply`, `PermissionV1.Rule`
- Runtime flow: OpenCode has wildcard rules, ask/reply lifecycle, once/always/reject replies, saved approvals, and deferred execution gating.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/permissions/models.py`
- `backend/app/permissions/policy.py`
- `backend/app/permissions/service.py`
- `backend/tests/test_permissions.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has wildcard rules, ask/reply lifecycle, once/always/reject replies, saved approvals, and deferred execution gating.
- Our Python platform has what: Python has default policy, destructive shell denial, external directory ASK, persisted permission_requests, audit rows, and approve/deny endpoints.
- Current behavior: Python has default policy, destructive shell denial, external directory ASK, persisted permission_requests, audit rows, and approve/deny endpoints.
- What is missing:
  - No wildcard ruleset used by policy
  - No once/always saved approvals
  - No runtime wait/resume after approval
  - No session-wide reject cascade
- What is weak:
  - matcher.py exists but policy uses fixed rules
  - Resolved permissions do not trigger execution
- Production risk: Permission prompts are auditable but operationally incomplete.
- Exact file to implement or polish next: `backend/app/permissions/service.py`
- Recommended action: Add saved approval rules and invoke run resume when a request is approved.
- Test that proves it works: Add backend/tests/test_permission_resume.py proving write.file waits, approve resumes, deny fails, and always approval skips future prompts.

### Gap Status

- Parity level: 55%
- Priority: P0
- Effort: M
- Owner area: permissions/runtime

## Subsystem 32: Permission request/approval flow

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/server/src/groups/v2/permission.ts`
- `external/opencode-source/packages/opencode/src/permission/index.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/run/permission.shared.ts`
- Responsibility: OpenCode lists/replies to permission requests by location/session and settles deferred execution with once/always/reject semantics.
- Important types/classes/functions: `PermissionGroup`, `SessionPermissionGroup`, `Permission.reply`
- Runtime flow: OpenCode lists/replies to permission requests by location/session and settles deferred execution with once/always/reject semantics.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/api/routes_permissions.py`
- `backend/app/permissions/service.py`
- `backend/app/runtime/tool_executor.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode lists/replies to permission requests by location/session and settles deferred execution with once/always/reject semantics.
- Our Python platform has what: Python has GET /permissions plus POST approve/deny endpoints backed by persisted rows and events.
- Current behavior: Python has GET /permissions plus POST approve/deny endpoints backed by persisted rows and events.
- What is missing:
  - No once/always/reject semantics
  - No resume of ToolCall.waiting_permission
  - No stale prompt timeout handling
  - No strong ownership check on request
- What is weak:
  - Approval returns only permission row
  - Denied request does not mark linked tool_call failed
- Production risk: Users can click Approve and still see the run stuck.
- Exact file to implement or polish next: `backend/app/api/routes_permissions.py`
- Recommended action: Resolve linked tool/run state inside approve/deny and schedule/resume execution.
- Test that proves it works: Add backend/tests/test_permissions_api.py proving approve moves tool_call and agent_run out of waiting_permission.

### Gap Status

- Parity level: 45%
- Priority: P0
- Effort: M
- Owner area: permissions/runtime

## Subsystem 33: Permission UI integration

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/context/permission.tsx`
- `external/opencode-source/packages/app/src/context/permission-auto-respond.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/run/footer.permission.tsx`
- Responsibility: OpenCode UI has permission context, auto-accept settings, event listener, once/always/reject replies, and CLI prompt footer.
- Important types/classes/functions: `PermissionProvider`, `autoRespondsPermission`, `respondOnce`
- Runtime flow: OpenCode UI has permission context, auto-accept settings, event listener, once/always/reject replies, and CLI prompt footer.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/styles/app.css`
- Current status: PARTIAL
- OpenCode has what: OpenCode UI has permission context, auto-accept settings, event listener, once/always/reject replies, and CLI prompt footer.
- Our Python platform has what: Python UI shows pending permission rows in global Permissions and Chat sidecar with Approve/Deny buttons.
- Current behavior: Python UI shows pending permission rows in global Permissions and Chat sidecar with Approve/Deny buttons.
- What is missing:
  - No once/always choice
  - No auto-approve setting
  - No modal with tool input preview
  - No resumed output after approval
- What is weak:
  - UI shows key/resource but not full risk context
  - Chat sidecar can miss global prompts
- Production risk: Users may approve risky operations without enough context or believe approval executed when it did not.
- Exact file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Recommended action: Add permission detail cards/modal with input preview and once/always/deny choices tied to backend resume.
- Test that proves it works: Add frontend test proving prompt appears from event and approve updates sidecar/tool status.

### Gap Status

- Parity level: 50%
- Priority: P0
- Effort: M
- Owner area: frontend/permissions

## Subsystem 34: Doom-loop/repeated action protection

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/core/test/session-runner.test.ts`
- Responsibility: OpenCode processor defines DOOM_LOOP_THRESHOLD=3 and can block repeated tool behavior.
- Important types/classes/functions: `DOOM_LOOP_THRESHOLD`, `ProcessorContext.blocked`
- Runtime flow: OpenCode processor defines DOOM_LOOP_THRESHOLD=3 and can block repeated tool behavior.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/runtime/loop_guard.py`
- `backend/app/runtime/tool_executor.py`
- `backend/tests/test_loop_guard.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode processor defines DOOM_LOOP_THRESHOLD=3 and can block repeated tool behavior.
- Our Python platform has what: Python LoopGuard hashes input_json and blocks same session+agent+tool+input on the third repeated attempt, emitting LOOP_GUARD_BLOCKED.
- Current behavior: Python LoopGuard hashes input_json and blocks same session+agent+tool+input on the third repeated attempt, emitting LOOP_GUARD_BLOCKED.
- What is missing:
  - No persisted denied ToolCall row for every loop guard path
  - No assistant-facing recovery message with alternatives
- What is weak:
  - Only exact JSON matches are blocked
  - Loop guard exception may skip audit log
- Production risk: Repeated harmful variants can still consume resources or mutate state.
- Exact file to implement or polish next: `backend/app/runtime/loop_guard.py`
- Recommended action: Persist loop-guard denials and normalize shell/file inputs before hashing.
- Test that proves it works: Extend backend/tests/test_loop_guard.py proving third repeat creates denied ToolCall and audit/system event.

### Gap Status

- Parity level: 75%
- Priority: P0
- Effort: S
- Owner area: runtime

## Subsystem 35: External directory protection

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/external-directory.ts`
- `external/opencode-source/packages/opencode/src/permission/index.ts`
- `external/opencode-source/packages/core/test/location-filesystem.test.ts`
- Responsibility: OpenCode has external directory permission behavior and location filesystem tests.
- Important types/classes/functions: `external-directory tool`, `Permission patterns`
- Runtime flow: OpenCode has external directory permission behavior and location filesystem tests.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/permissions/policy.py`
- `backend/app/tools/base.py`
- `backend/tests/test_permissions.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode has external directory permission behavior and location filesystem tests.
- Our Python platform has what: Python policy detects absolute resources outside workspace_root and asks with permission_key external_directory.
- Current behavior: Python policy detects absolute resources outside workspace_root and asks with permission_key external_directory.
- What is missing:
  - No external-directory saved allow rules
  - No symlink escape checks at execution time
  - No UI warning specific to external paths
- What is weak:
  - Comma-split resource parsing can mis-handle commas in paths
  - Shell commands are not path-parsed
- Production risk: Some external access can slip through shell commands or symlinks.
- Exact file to implement or polish next: `backend/app/permissions/policy.py`
- Recommended action: Centralize resolved path authority checks and call it from every file and shell tool.
- Test that proves it works: Add backend/tests/test_external_directory.py proving file, patch, glob, grep, and shell workdirs outside workspace ask or deny consistently.

### Gap Status

- Parity level: 65%
- Priority: P0
- Effort: S
- Owner area: permissions/tools

## Subsystem 36: Environment/secret file protection

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/env.ts`
- `external/opencode-source/packages/opencode/src/auth/index.ts`
- `external/opencode-source/packages/opencode/src/provider/auth.ts`
- `external/opencode-source/packages/core/test/policy.test.ts`
- Responsibility: OpenCode handles environment/auth/provider credentials through dedicated layers and policy tests.
- Important types/classes/functions: `Env`, `Auth`, `Provider auth`
- Runtime flow: OpenCode handles environment/auth/provider credentials through dedicated layers and policy tests.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/permissions/policy.py`
- `backend/app/tools/read.py`
- `backend/app/tools/write.py`
- Current status: MISSING
- OpenCode has what: OpenCode handles environment/auth/provider credentials through dedicated layers and policy tests.
- Our Python platform has what: Python has no dedicated secret-file policy beyond external directory and destructive shell checks.
- Current behavior: Python has no dedicated secret-file policy beyond external directory and destructive shell checks.
- What is missing:
  - No ask/deny patterns for .env, keys, certs, SSH, tokens, or cloud credentials
  - No redaction in tool output/model_call request_json
  - No secret scanning before writes
- What is weak:
  - Workspace .env is currently normal read.file because read.file is allowed
- Production risk: Secrets can be read into model prompts, persisted, and displayed in UI.
- Exact file to implement or polish next: `backend/app/permissions/secret_policy.py`
- Recommended action: Implement secret path/content detection and redact sensitive values in tool/model/audit payloads.
- Test that proves it works: Add backend/tests/test_secret_policy.py proving .env/private-key reads ask or deny and outputs are redacted.

### Gap Status

- Parity level: 15%
- Priority: P0
- Effort: M
- Owner area: security/tools

## Subsystem 37: Audit logging

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/opencode/src/permission/index.ts`
- `external/opencode-source/packages/opencode/src/storage/schema.ts`
- `external/opencode-source/packages/core/test/event.test.ts`
- Responsibility: OpenCode emits typed events for session/tool/permission lifecycle and persists local runtime state.
- Important types/classes/functions: `EventV2`, `SessionEvent`, `Permission.Event`
- Runtime flow: OpenCode emits typed events for session/tool/permission lifecycle and persists local runtime state.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/db/models.py`
- `backend/app/runtime/tool_executor.py`
- `backend/app/permissions/service.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode emits typed events for session/tool/permission lifecycle and persists local runtime state.
- Our Python platform has what: Python has AuditLog plus audit rows for tool execute success/failure/denial and permission request/approve/deny.
- Current behavior: Python has AuditLog plus audit rows for tool execute success/failure/denial and permission request/approve/deny.
- What is missing:
  - No audit on model calls, session creation, message creation, artifact operations, or loop guard denial
  - No actor/IP propagation
  - No audit query API
- What is weak:
  - Audit metadata is unredacted JSON
  - resource_id is not FK-linked
- Production risk: Security investigations will miss who prompted, which model was called, and what data was exposed.
- Exact file to implement or polish next: `backend/app/audit/service.py`
- Recommended action: Centralize audit logging and call it from session, message, model, tool, permission, and artifact services with redaction.
- Test that proves it works: Add backend/tests/test_audit_logs.py proving every tool permission decision and model call writes one redacted audit row.

### Gap Status

- Parity level: 45%
- Priority: P0
- Effort: M
- Owner area: backend/database

## Subsystem 38: Storage/database schema

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/storage/schema.ts`
- `external/opencode-source/packages/core/src/session/sql.ts`
- `external/opencode-source/packages/core/src/project/sql.ts`
- `external/opencode-source/packages/effect-drizzle-sqlite/test/sqlite.test.ts`
- Responsibility: OpenCode persists local-first runtime state in SQLite/Drizzle with session/project/part/event storage abstractions.
- Important types/classes/functions: `SessionTable`, `PartTable`, `ProjectTable`, `Storage`
- Runtime flow: OpenCode persists local-first runtime state in SQLite/Drizzle with session/project/part/event storage abstractions.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/db/models.py`
- `backend/app/db/postgres.py`
- `backend/app/db/migrations/versions/202606050001_initial_schema.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode persists local-first runtime state in SQLite/Drizzle with session/project/part/event storage abstractions.
- Our Python platform has what: Python has PostgreSQL/pgvector SQLAlchemy models for the required production tables and async database access.
- Current behavior: Python has PostgreSQL/pgvector SQLAlchemy models for the required production tables and async database access.
- What is missing:
  - No enum/check constraints for status fields
  - No FK from permission_requests.tool_call_id to tool_calls.id
  - No row-level security
  - No ClickHouse event migration
- What is weak:
  - Some common query IDs lack indexes
  - updated_at relies on ORM/raw defaults without triggers
- Production risk: Integrity bugs can appear under concurrent and multi-tenant usage.
- Exact file to implement or polish next: `backend/app/db/migrations/versions/202606050002_integrity_constraints.py`
- Recommended action: Add constraints, FK links, enums/checks, and tenant-aware indexes.
- Test that proves it works: Add backend/tests/test_db_integrity.py proving invalid statuses and orphan permission tool_call IDs are rejected.

### Gap Status

- Parity level: 75%
- Priority: P1
- Effort: M
- Owner area: database

## Subsystem 39: Migrations

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/storage/schema.ts`
- `external/opencode-source/packages/core/test/database-migration.test.ts`
- `external/opencode-source/packages/effect-drizzle-sqlite/test/sqlite.test.ts`
- Responsibility: OpenCode has tested schema evolution around local SQLite storage.
- Important types/classes/functions: `database migration tests`, `Storage schema`
- Runtime flow: OpenCode has tested schema evolution around local SQLite storage.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/alembic.ini`
- `backend/app/db/migrations/env.py`
- `backend/app/db/migrations/versions/202606050001_initial_schema.py`
- `scripts/migrate.sh`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode has tested schema evolution around local SQLite storage.
- Our Python platform has what: Python has Alembic environment and one initial migration creating all required production tables/extensions.
- Current behavior: Python has Alembic environment and one initial migration creating all required production tables/extensions.
- What is missing:
  - No downgrade coverage
  - No migration CI test against fresh Postgres
  - No seed/bootstrap migration separation
- What is weak:
  - Initial migration is large and raw SQL-heavy
  - No model-vs-migration drift check
- Production risk: Future schema changes can drift silently from SQLAlchemy models.
- Exact file to implement or polish next: `backend/tests/test_migrations.py`
- Recommended action: Add migration smoke tests and model-vs-migration drift checks.
- Test that proves it works: Add backend/tests/test_migrations.py proving upgrade head on empty Postgres and expected tables/constraints exist.

### Gap Status

- Parity level: 70%
- Priority: P1
- Effort: M
- Owner area: database/infra

## Subsystem 40: Artifact storage

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/tool/truncate.ts`
- `external/opencode-source/packages/opencode/src/tool/truncation-dir.ts`
- `external/opencode-source/packages/core/test/tool-output-store.test.ts`
- Responsibility: OpenCode stores/truncates large tool output and references attachments/metadata.
- Important types/classes/functions: `ToolOutput`, `truncate.output`, `tool-output-store tests`
- Runtime flow: OpenCode stores/truncates large tool output and references attachments/metadata.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/artifacts/minio_store.py`
- `backend/app/artifacts/artifact_service.py`
- `backend/app/db/models.py`
- `backend/app/api/routes_artifacts.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode stores/truncates large tool output and references attachments/metadata.
- Our Python platform has what: Python has Artifact table, MinIO health client, artifact listing API, and ToolResult.artifacts field.
- Current behavior: Python has Artifact table, MinIO health client, artifact listing API, and ToolResult.artifacts field.
- What is missing:
  - No upload/download API
  - No presigned URLs
  - No ToolExecutor artifact persistence
  - No UI preview/download action
- What is weak:
  - ArtifactService is list-only
  - ToolResult.artifacts are not normalized after execution
- Production risk: Large outputs and generated files remain trapped in text or local filesystem.
- Exact file to implement or polish next: `backend/app/artifacts/artifact_service.py`
- Recommended action: Implement MinIO put/get/presign and persist ToolResult.artifacts from ToolExecutor.
- Test that proves it works: Add backend/tests/test_artifacts.py proving artifact upload, persistence, list, and download.

### Gap Status

- Parity level: 45%
- Priority: P1
- Effort: M
- Owner area: artifacts/tools

## Subsystem 41: Memory/vector storage

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/summary.ts`
- `external/opencode-source/packages/opencode/src/reference/reference.ts`
- `external/opencode-source/packages/core/test/system-context.test.ts`
- Responsibility: OpenCode gathers reference/context data for prompt construction rather than pgvector/Qdrant as core storage.
- Important types/classes/functions: `Reference service`, `SessionSummary`, `System context`
- Runtime flow: OpenCode gathers reference/context data for prompt construction rather than pgvector/Qdrant as core storage.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/memory/pgvector_store.py`
- `backend/app/memory/qdrant_store.py`
- `backend/app/memory/memory_service.py`
- `backend/app/db/models.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode gathers reference/context data for prompt construction rather than pgvector/Qdrant as core storage.
- Our Python platform has what: Python has MemoryItem with pgvector column plus Qdrant health/client boundaries.
- Current behavior: Python has MemoryItem with pgvector column plus Qdrant health/client boundaries.
- What is missing:
  - No embedding provider
  - No memory write/read API
  - No Qdrant collection management
  - No retrieval in context builder
- What is weak:
  - Vector dimension fixed at 1536 without Ollama embedding decision
  - memory_service.py is empty
- Production risk: Memory infrastructure exists but agents cannot use it.
- Exact file to implement or polish next: `backend/app/memory/memory_service.py`
- Recommended action: Implement memory ingestion/retrieval and inject snippets into context builder.
- Test that proves it works: Add backend/tests/test_memory_service.py proving memory insert, vector search mock, and context retrieval.

### Gap Status

- Parity level: 25%
- Priority: P2
- Effort: L
- Owner area: memory/runtime

## Subsystem 42: Graph storage

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/reference/reference.ts`
- `external/opencode-source/packages/core/test/project-reference.test.ts`
- `external/opencode-source/packages/core/test/repository.test.ts`
- Responsibility: OpenCode resolves file/project/repository relationships through local services, not Neo4j.
- Important types/classes/functions: `Reference service`, `Repository cache`
- Runtime flow: OpenCode resolves file/project/repository relationships through local services, not Neo4j.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/memory/graph_store.py`
- `docker-compose.yml`
- Current status: PARTIAL
- OpenCode has what: OpenCode resolves file/project/repository relationships through local services, not Neo4j.
- Our Python platform has what: Python has Neo4j Docker service and a graph_store health boundary.
- Current behavior: Python has Neo4j Docker service and a graph_store health boundary.
- What is missing:
  - No graph schema
  - No Cypher repository layer
  - No ingestion from file scans/tool calls
  - No agent context usage
- What is weak:
  - Neo4j is operationally present but unused
- Production risk: Graph service consumes resources without platform behavior.
- Exact file to implement or polish next: `backend/app/memory/graph_store.py`
- Recommended action: Define graph nodes and relationships for projects, files, symbols, sessions, tools, and workflows.
- Test that proves it works: Add backend/tests/test_graph_store.py proving health, upsert, and traversal with mocked Neo4j session.

### Gap Status

- Parity level: 25%
- Priority: P2
- Effort: L
- Owner area: memory/infra

## Subsystem 43: Queue/worker runtime

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/background/job.ts`
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/core/test/session-run-coordinator.test.ts`
- Responsibility: OpenCode has background jobs and session run coordination beyond one request.
- Important types/classes/functions: `BackgroundJob`, `Session run coordinator`
- Runtime flow: OpenCode has background jobs and session run coordination beyond one request.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/queue/redis_client.py`
- `backend/app/queue/worker.py`
- `backend/app/api/routes_messages.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has background jobs and session run coordination beyond one request.
- Our Python platform has what: Python has Redis health/client boundary and empty worker module; messages invoke AgentRunner synchronously.
- Current behavior: Python has Redis health/client boundary and empty worker module; messages invoke AgentRunner synchronously.
- What is missing:
  - No Redis queue
  - No worker process command
  - No distributed locks
  - No retry/dead-letter semantics
  - No cancellation
- What is weak:
  - HTTP request blocks during model/tool loop
  - Permission waits return before a worker can resume
- Production risk: Runs cannot survive restarts or scale horizontally.
- Exact file to implement or polish next: `backend/app/queue/worker.py`
- Recommended action: Move agent execution into Redis-backed worker with locks and resumable jobs.
- Test that proves it works: Add backend/tests/test_worker_runtime.py proving enqueue, worker execution, retry, and permission resume.

### Gap Status

- Parity level: 25%
- Priority: P1
- Effort: L
- Owner area: runtime/queue

## Subsystem 44: ClickHouse/event analytics

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/server/event.ts`
- `external/opencode-source/packages/core/test/event.test.ts`
- Responsibility: OpenCode has operational event streams and tests; ClickHouse is not a direct OpenCode requirement.
- Important types/classes/functions: `EventV2`, `event tests`
- Runtime flow: OpenCode has operational event streams and tests; ClickHouse is not a direct OpenCode requirement.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/analytics/clickhouse.py`
- `backend/app/analytics/event_writer.py`
- `docker-compose.yml`
- Current status: PARTIAL
- OpenCode has what: OpenCode has operational event streams and tests; ClickHouse is not a direct OpenCode requirement.
- Our Python platform has what: Python has ClickHouse service, health check, and placeholder event_writer boundary.
- Current behavior: Python has ClickHouse service, health check, and placeholder event_writer boundary.
- What is missing:
  - No ClickHouse schema migration
  - No event writer invocation
  - No analytics API or dashboard
- What is weak:
  - ClickHouse is infrastructure-only and not connected to SystemEvent
- Production risk: Observability promises are not fulfilled and system_events may grow without analytics offload.
- Exact file to implement or polish next: `backend/app/analytics/event_writer.py`
- Recommended action: Define ClickHouse event table and mirror SystemEvent rows asynchronously.
- Test that proves it works: Add backend/tests/test_event_writer.py proving event_writer serializes SystemEvent to ClickHouse insert payload.

### Gap Status

- Parity level: 25%
- Priority: P2
- Effort: M
- Owner area: analytics/infra

## Subsystem 45: Plugin system

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/plugin/index.ts`
- `external/opencode-source/packages/opencode/src/plugin/loader.ts`
- `external/opencode-source/packages/plugin/src/index.ts`
- `external/opencode-source/packages/plugin/src/tool.ts`
- `external/opencode-source/packages/core/test/plugin.test.ts`
- Responsibility: OpenCode loads plugins, hooks, plugin-defined tools, and provider integrations with tests.
- Important types/classes/functions: `Plugin.Service`, `Plugin hooks`, `ToolDefinition`
- Runtime flow: OpenCode loads plugins, hooks, plugin-defined tools, and provider integrations with tests.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/plugins/loader.py`
- `backend/app/plugins/hooks.py`
- `backend/app/db/models.py`
- Current status: MISSING
- OpenCode has what: OpenCode loads plugins, hooks, plugin-defined tools, and provider integrations with tests.
- Our Python platform has what: Python has Plugin table and placeholder loader/hooks modules that defer execution until a sandbox/trust model exists.
- Current behavior: Python has Plugin table and placeholder loader/hooks modules that defer execution until a sandbox/trust model exists.
- What is missing:
  - No plugin manifest schema
  - No loader
  - No hook dispatch
  - No sandbox
  - No plugin tool registration
- What is weak:
  - Database rows may imply a capability that runtime does not provide
- Production risk: Unsafe plugin execution would be a critical vulnerability if added casually.
- Exact file to implement or polish next: `backend/app/plugins/loader.py`
- Recommended action: Define plugin manifest and trust model before enabling execution; start with signed/local metadata only.
- Test that proves it works: Add backend/tests/test_plugin_loader.py proving disabled plugins do not load and invalid manifests are rejected.

### Gap Status

- Parity level: 15%
- Priority: P2
- Effort: XL
- Owner area: plugins/security

## Subsystem 46: MCP integration

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/mcp/index.ts`
- `external/opencode-source/packages/opencode/src/mcp/auth.ts`
- `external/opencode-source/packages/opencode/src/mcp/oauth-provider.ts`
- `external/opencode-source/packages/server/src/groups/v2/skill.ts`
- Responsibility: OpenCode has MCP registration/auth/OAuth surfaces integrated with tools/skills.
- Important types/classes/functions: `MCP service`, `OAuth provider`, `MCP auth`
- Runtime flow: OpenCode has MCP registration/auth/OAuth surfaces integrated with tools/skills.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/mcp/client.py`
- `backend/app/mcp/registry.py`
- `backend/app/db/models.py`
- Current status: MISSING
- OpenCode has what: OpenCode has MCP registration/auth/OAuth surfaces integrated with tools/skills.
- Our Python platform has what: Python has McpServer table plus placeholder client/registry modules.
- Current behavior: Python has McpServer table plus placeholder client/registry modules.
- What is missing:
  - No stdio/SSE/HTTP MCP client
  - No server lifecycle
  - No tool registration
  - No permission mapping
  - No UI management
- What is weak:
  - MCP rows cannot be used by agents
- Production risk: Later MCP could bypass permission/audit if not wrapped through ToolExecutor.
- Exact file to implement or polish next: `backend/app/mcp/client.py`
- Recommended action: Implement MCP client with tool discovery feeding ToolRegistry and permission/audit wrapping.
- Test that proves it works: Add backend/tests/test_mcp_registry.py with a fake MCP server exposing one permission-checked tool.

### Gap Status

- Parity level: 10%
- Priority: P2
- Effort: XL
- Owner area: mcp/tools

## Subsystem 47: GitHub workflow/bot integration

### OpenCode Reference

Files inspected:
- `external/opencode-source/.github/workflows/triage.yml`
- `external/opencode-source/.github/workflows/review.yml`
- `external/opencode-source/packages/opencode/src/cli/cmd/github.ts`
- `external/opencode-source/.opencode/tool/github-triage.ts`
- Responsibility: OpenCode includes GitHub action automation, CLI commands, and custom tools for triage/review workflows.
- Important types/classes/functions: `github CLI commands`, `GitHub workflows`, `custom GitHub tools`
- Runtime flow: OpenCode includes GitHub action automation, CLI commands, and custom tools for triage/review workflows.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `scripts`
- `backend/app/cli.py`
- Current status: NOT_APPLICABLE
- OpenCode has what: OpenCode includes GitHub action automation, CLI commands, and custom tools for triage/review workflows.
- Our Python platform has what: Python platform has no GitHub bot/workflow integration, which is outside local-first runtime v1.
- Current behavior: Python platform has no GitHub bot/workflow integration, which is outside local-first runtime v1.
- What is missing:
  - No GitHub App/auth/workflows by design
- What is weak:
  - None for current target if GitHub automation remains out of scope
- Production risk: If later added, repository write permissions need separate auth/approval design.
- Exact file to implement or polish next: `docs/architecture/github-integration.md`
- Recommended action: Ignore for now and revisit as a separate integration after core runtime safety.
- Test that proves it works: No current runtime test required; future integration should use mocked GitHub API contract tests.

### Gap Status

- Parity level: 5%
- Priority: P3
- Effort: L
- Owner area: integrations

## Subsystem 48: CLI client

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/cli/bootstrap.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/run.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/session.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/models.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/mcp.ts`
- Responsibility: OpenCode CLI supports run, serve, sessions, models, providers, MCP, plugins, GitHub, import/export, debug, and TUI.
- Important types/classes/functions: `CLI commands`, `run runtime`, `session commands`
- Runtime flow: OpenCode CLI supports run, serve, sessions, models, providers, MCP, plugins, GitHub, import/export, debug, and TUI.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/cli.py`
- `pyproject.toml`
- Current status: PARTIAL
- OpenCode has what: OpenCode CLI supports run, serve, sessions, models, providers, MCP, plugins, GitHub, import/export, debug, and TUI.
- Our Python platform has what: Python Typer CLI exposes serve and migrate only.
- Current behavior: Python Typer CLI exposes serve and migrate only.
- What is missing:
  - No chat/run command
  - No session list/detail command
  - No model list/pull command
  - No permission response command
  - No smoke/debug commands
- What is weak:
  - migrate uses subprocess without structured errors
  - No CLI tests
- Production risk: Operators must use HTTP/UI even when UI is down.
- Exact file to implement or polish next: `backend/app/cli.py`
- Recommended action: Add Typer commands for health, models, sessions, send, and permissions.
- Test that proves it works: Add backend/tests/test_cli.py using Typer CliRunner for serve config and models/session commands.

### Gap Status

- Parity level: 30%
- Priority: P2
- Effort: L
- Owner area: cli

## Subsystem 49: TUI client

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/cli/cmd/tui/app.tsx`
- `external/opencode-source/packages/opencode/src/cli/cmd/tui/event.ts`
- `external/opencode-source/packages/opencode/src/cli/cmd/run/footer.permission.tsx`
- `external/opencode-source/packages/plugin/src/tui.ts`
- Responsibility: OpenCode includes terminal UI code under its CLI and plugin TUI API.
- Important types/classes/functions: `TUI app`, `TUI event bridge`, `plugin TUI`
- Runtime flow: OpenCode includes terminal UI code under its CLI and plugin TUI API.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/cli.py`
- Current status: NOT_APPLICABLE
- OpenCode has what: OpenCode includes terminal UI code under its CLI and plugin TUI API.
- Our Python platform has what: Python has no Textual/Rich TUI beyond simple Typer CLI; Web UI is the required first client.
- Current behavior: Python has no Textual/Rich TUI beyond simple Typer CLI; Web UI is the required first client.
- What is missing:
  - No TUI, intentionally deferred
- What is weak:
  - Headless interactive control is limited until CLI grows
- Production risk: Headless users have less interactive control than OpenCode users.
- Exact file to implement or polish next: `docs/architecture/tui-future.md`
- Recommended action: Ignore for production v1; revisit with Textual after backend runtime and Web UI are stable.
- Test that proves it works: No current test required; future TUI should have event rendering snapshot tests.

### Gap Status

- Parity level: 0%
- Priority: P3
- Effort: XL
- Owner area: cli/frontend

## Subsystem 50: Web UI dashboard

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/pages/layout.tsx`
- `external/opencode-source/packages/app/src/pages/home.tsx`
- `external/opencode-source/packages/app/src/pages/layout/sidebar-shell.tsx`
- `external/opencode-source/packages/app/src/context/server-sync.tsx`
- Responsibility: OpenCode app shell has project/workspace navigation, sync contexts, settings dialogs, file tree, session panels, and status surfaces.
- Important types/classes/functions: `Layout page`, `ServerSync context`, `Sidebar shell`
- Runtime flow: OpenCode app shell has project/workspace navigation, sync contexts, settings dialogs, file tree, session panels, and status surfaces.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/App.tsx`
- `frontend/src/styles/app.css`
- Current status: PARTIAL
- OpenCode has what: OpenCode app shell has project/workspace navigation, sync contexts, settings dialogs, file tree, session panels, and status surfaces.
- Our Python platform has what: Python frontend has React dashboard tabs for Chat, Sessions, Agents, Tools, Permissions, Ollama, Artifacts, and Events.
- Current behavior: Python frontend has React dashboard tabs for Chat, Sessions, Agents, Tools, Permissions, Ollama, Artifacts, and Events.
- What is missing:
  - No project/workspace navigation
  - No settings dialogs
  - No file tree or diff view
  - No generated client/store architecture
- What is weak:
  - Dashboard.tsx is a large single component
  - Polling and WebSocket state are mixed into one page
- Production risk: Feature growth will make the UI hard to maintain.
- Exact file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Recommended action: Split Dashboard into page components and shared stores before adding more runtime UI.
- Test that proves it works: Add frontend component tests proving each tab renders with mocked API data.

### Gap Status

- Parity level: 55%
- Priority: P1
- Effort: L
- Owner area: frontend

## Subsystem 51: Session detail/chat UI

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/pages/session.tsx`
- `external/opencode-source/packages/app/src/pages/session/message-timeline.tsx`
- `external/opencode-source/packages/app/src/components/prompt-input.tsx`
- `external/opencode-source/packages/app/src/pages/session/session-side-panel.tsx`
- Responsibility: OpenCode session page has timeline, composer, side panels, terminal/review tabs, model sync, history loading, and live events.
- Important types/classes/functions: `MessageTimeline`, `PromptInput`, `SessionSidePanel`, `createSessionComposerState`
- Runtime flow: OpenCode session page has timeline, composer, side panels, terminal/review tabs, model sync, history loading, and live events.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/styles/app.css`
- Current status: PARTIAL
- OpenCode has what: OpenCode session page has timeline, composer, side panels, terminal/review tabs, model sync, history loading, and live events.
- Our Python platform has what: Python UI has Sessions page and Codex-style Chat with Ollama model picker, transcript, composer, permissions, tool calls, and live events.
- Current behavior: Python UI has Sessions page and Codex-style Chat with Ollama model picker, transcript, composer, permissions, tool calls, and live events.
- What is missing:
  - No streaming assistant text
  - No structured tool/reasoning/artifact rendering
  - No chat session persistence selector
  - No markdown/code rendering
- What is weak:
  - Chat uses general agent with edit tools
  - Error state can reflect protocol fallback instead of clear mode
- Production risk: Users may expect safe chat but start a tool-capable session.
- Exact file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Recommended action: Create a dedicated chat-safe agent/profile and render structured message/tool/permission parts.
- Test that proves it works: Add frontend test proving /models populates dropdown and send payload includes model_name for new/existing chats.

### Gap Status

- Parity level: 60%
- Priority: P0
- Effort: M
- Owner area: frontend/runtime

## Subsystem 52: Agent/tool management UI

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/components/dialog-settings.tsx`
- `external/opencode-source/packages/app/src/components/settings-models.tsx`
- `external/opencode-source/packages/app/src/utils/agent.ts`
- Responsibility: OpenCode has settings/model/provider dialogs and agent utility surfaces.
- Important types/classes/functions: `settings dialogs`, `agent utilities`
- Runtime flow: OpenCode has settings/model/provider dialogs and agent utility surfaces.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `backend/app/api/routes_agents.py`
- `backend/app/api/routes_tools.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has settings/model/provider dialogs and agent utility surfaces.
- Our Python platform has what: Python Agents and Tools tabs list definitions and metadata only.
- Current behavior: Python Agents and Tools tabs list definitions and metadata only.
- What is missing:
  - No create/edit/disable agent UI
  - No tool permission override UI
  - No plugin/MCP tool management
- What is weak:
  - Tool schemas are not expandable
  - Hidden agents are not manageable
- Production risk: Operators cannot safely tune runtime without editing code.
- Exact file to implement or polish next: `frontend/src/pages/AgentsPage.tsx`
- Recommended action: Split management pages and add read-only detail drawers before config APIs.
- Test that proves it works: Add frontend tests proving detail drawers show allowed tools, permission profile, and JSON schema.

### Gap Status

- Parity level: 35%
- Priority: P2
- Effort: M
- Owner area: frontend/backend

## Subsystem 53: Model status UI

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/components/dialog-select-model.tsx`
- `external/opencode-source/packages/app/src/components/dialog-manage-models.tsx`
- `external/opencode-source/packages/app/src/context/models.tsx`
- `external/opencode-source/packages/opencode/src/provider/model-status.ts`
- Responsibility: OpenCode has model dialogs, model context, provider status, and model management flows.
- Important types/classes/functions: `models context`, `model status`, `select/manage dialogs`
- Runtime flow: OpenCode has model dialogs, model context, provider status, and model management flows.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `backend/app/api/routes_models.py`
- `backend/app/providers/ollama.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode has model dialogs, model context, provider status, and model management flows.
- Our Python platform has what: Python Ollama tab lists models from /models and Chat dropdown uses all installed host Ollama tags.
- Current behavior: Python Ollama tab lists models from /models and Chat dropdown uses all installed host Ollama tags.
- What is missing:
  - No pull progress UI
  - No model capability labels
  - No per-model health/status history
  - No selected default model setting
- What is weak:
  - Cloud-looking Ollama tags are not labeled but remain selectable by user requirement
  - Model size unknown renders plainly
- Production risk: Users cannot tell which models are tool-capable or currently reachable beyond dependency health.
- Exact file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Recommended action: Add model detail labels from provider capability metadata without filtering selectable Ollama tags.
- Test that proves it works: Add frontend model UI test proving cloud/local tags appear and selected model is sent unchanged.

### Gap Status

- Parity level: 70%
- Priority: P1
- Effort: M
- Owner area: frontend/backend

## Subsystem 54: Permission prompt UI

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/context/permission.tsx`
- `external/opencode-source/packages/opencode/src/cli/cmd/run/footer.permission.tsx`
- `external/opencode-source/packages/app/src/context/permission-auto-respond.ts`
- Responsibility: OpenCode has interactive permission prompts with auto-respond and once/always/reject flows.
- Important types/classes/functions: `PermissionProvider`, `footer.permission`, `autoRespondsPermission`
- Runtime flow: OpenCode has interactive permission prompts with auto-respond and once/always/reject flows.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/api/client.ts`
- Current status: PARTIAL
- OpenCode has what: OpenCode has interactive permission prompts with auto-respond and once/always/reject flows.
- Our Python platform has what: Python shows pending permissions in global Permissions and Chat sidecar with Approve/Deny buttons.
- Current behavior: Python shows pending permissions in global Permissions and Chat sidecar with Approve/Deny buttons.
- What is missing:
  - No input diff preview
  - No once/always controls
  - No auto-approve settings
  - No visual indication approval resumed or failed execution
- What is weak:
  - Prompt context is too thin for destructive operations
  - Buttons can be clicked repeatedly
- Production risk: Users may approve without understanding effect or get stuck after approval.
- Exact file to implement or polish next: `frontend/src/components/PermissionPrompt.tsx`
- Recommended action: Add reusable permission prompt component with preview, risk labels, and once/always/deny actions.
- Test that proves it works: Add frontend PermissionPrompt test covering approve, deny, duplicate-click disabled state, and risk preview.

### Gap Status

- Parity level: 50%
- Priority: P0
- Effort: M
- Owner area: frontend/permissions

## Subsystem 55: Logs/events UI

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/app/src/components/status-popover.tsx`
- `external/opencode-source/packages/app/src/components/titlebar-session-events.ts`
- `external/opencode-source/packages/app/src/context/global-sync/event-reducer.ts`
- Responsibility: OpenCode status/event UI is driven by typed server-sync reducers and titlebar/session event helpers.
- Important types/classes/functions: `status popover`, `titlebar-session-events`, `event reducer`
- Runtime flow: OpenCode status/event UI is driven by typed server-sync reducers and titlebar/session event helpers.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `frontend/src/pages/Dashboard.tsx`
- `backend/app/api/routes_system_events.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode status/event UI is driven by typed server-sync reducers and titlebar/session event helpers.
- Our Python platform has what: Python Events tab lists SystemEvent rows and Chat sidecar shows recent live session events.
- Current behavior: Python Events tab lists SystemEvent rows and Chat sidecar shows recent live session events.
- What is missing:
  - No filtering by severity/type/session
  - No event detail payload expansion
  - No audit log UI
  - No pagination
- What is weak:
  - Events tab renders raw JSON and can grow noisy
  - No correlation view across run/model/tool
- Production risk: Operators cannot quickly diagnose failed runs in production.
- Exact file to implement or polish next: `frontend/src/pages/EventsPage.tsx`
- Recommended action: Split events page with filters, detail drawer, and correlation IDs.
- Test that proves it works: Add frontend EventsPage test proving severity/type filters and payload detail toggle.

### Gap Status

- Parity level: 55%
- Priority: P1
- Effort: M
- Owner area: frontend/backend

## Subsystem 56: Testing coverage

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/core/test/session-runner.test.ts`
- `external/opencode-source/packages/core/test/tool-read.test.ts`
- `external/opencode-source/packages/core/test/tool-write.test.ts`
- `external/opencode-source/packages/core/test/permission.test.ts`
- `external/opencode-source/packages/llm/test/tool-runtime.test.ts`
- `external/opencode-source/packages/app/src/context/permission-auto-respond.test.ts`
- Responsibility: OpenCode has broad tests across session runner, tools, permissions, LLM adapters, events, file mutation, app utilities, and migrations.
- Important types/classes/functions: `session-runner tests`, `tool tests`, `permission tests`, `llm tests`
- Runtime flow: OpenCode has broad tests across session runner, tools, permissions, LLM adapters, events, file mutation, app utilities, and migrations.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/tests/test_permissions.py`
- `backend/tests/test_health.py`
- `backend/tests/test_ollama_provider.py`
- `backend/tests/test_agent_registry.py`
- `backend/tests/test_loop_guard.py`
- `backend/tests/test_sessions.py`
- `backend/tests/test_agent_loop.py`
- `backend/tests/test_tool_registry.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has broad tests across session runner, tools, permissions, LLM adapters, events, file mutation, app utilities, and migrations.
- Our Python platform has what: Python has focused pytest coverage for health, provider mock behavior, registries, permissions, loop guard, session serialization, and JSON parsing.
- Current behavior: Python has focused pytest coverage for health, provider mock behavior, registries, permissions, loop guard, session serialization, and JSON parsing.
- What is missing:
  - No dependency integration tests
  - No frontend tests
  - No tool execution persistence tests
  - No permission approval/resume tests
  - No migration tests
- What is weak:
  - Several tests validate serializers/helpers rather than DB behavior
  - No CI config evident
- Production risk: Core agent safety regressions can ship unnoticed.
- Exact file to implement or polish next: `backend/tests/test_permission_resume.py`
- Recommended action: Add high-risk integration tests first: permission resume, mutation tools, context builder, migrations, and frontend chat model picker.
- Test that proves it works: The new tests plus dockerized smoke-test must pass before implementation work continues.

### Gap Status

- Parity level: 45%
- Priority: P0
- Effort: L
- Owner area: tests

## Subsystem 57: Docker/dependency orchestration

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/cli/cmd/serve.ts`
- `external/opencode-source/packages/opencode/src/server/server.ts`
- `external/opencode-source/package.json`
- Responsibility: OpenCode is locally orchestrated through CLI/package scripts rather than Docker-first infrastructure.
- Important types/classes/functions: `serve command`, `package scripts`
- Runtime flow: OpenCode is locally orchestrated through CLI/package scripts rather than Docker-first infrastructure.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `docker-compose.yml`
- `Dockerfile.backend`
- `Dockerfile.frontend`
- `.env.example`
- `scripts/dev-up.sh`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode is locally orchestrated through CLI/package scripts rather than Docker-first infrastructure.
- Our Python platform has what: Python Docker Compose includes backend, frontend, Postgres/pgvector, Redis, Qdrant, Neo4j, MinIO, ClickHouse, optional Docker Ollama, and host Ollama routing.
- Current behavior: Python Docker Compose includes backend, frontend, Postgres/pgvector, Redis, Qdrant, Neo4j, MinIO, ClickHouse, optional Docker Ollama, and host Ollama routing.
- What is missing:
  - No production override file
  - No secrets management
  - No resource limits
  - No backend worker service
- What is weak:
  - Default service passwords are development-grade
  - ollama_data volume remains declared although Docker Ollama is optional
- Production risk: Developers may mistake dev Compose for production deployment.
- Exact file to implement or polish next: `docker-compose.yml`
- Recommended action: Add dev/production compose profiles and a worker service once queue runtime exists.
- Test that proves it works: Extend scripts/smoke-test.sh proving compose health and host Ollama routing with docker profile disabled.

### Gap Status

- Parity level: 80%
- Priority: P1
- Effort: M
- Owner area: infra

## Subsystem 58: Health checks

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/server/src/groups/v2/health.ts`
- `external/opencode-source/packages/server/src/handlers/v2/health.ts`
- `external/opencode-source/packages/app/src/utils/server-health.test.ts`
- Responsibility: OpenCode has health route group and app utilities/tests around server health.
- Important types/classes/functions: `HealthGroup`, `server health utilities`
- Runtime flow: OpenCode has health route group and app utilities/tests around server health.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/api/routes_health.py`
- `backend/app/db/postgres.py`
- `backend/app/queue/redis_client.py`
- `backend/app/providers/ollama.py`
- `docker-compose.yml`
- `backend/tests/test_health.py`
- Current status: EXISTS_NEEDS_POLISH
- OpenCode has what: OpenCode has health route group and app utilities/tests around server health.
- Our Python platform has what: Python has /health and /health/dependencies for all required infra plus Docker healthchecks.
- Current behavior: Python has /health and /health/dependencies for all required infra plus Docker healthchecks.
- What is missing:
  - No readiness vs liveness split
  - No migration version in health
  - No per-dependency latency
  - No auth on detailed dependency output
- What is weak:
  - Backend Docker health only checks /health
  - Detailed errors may expose internal endpoints
- Production risk: Orchestrators can route traffic to an app whose dependencies are degraded.
- Exact file to implement or polish next: `backend/app/api/routes_health.py`
- Recommended action: Add /health/live and /health/ready with migration/dependency readiness and sanitized output.
- Test that proves it works: Extend backend/tests/test_health.py proving ready is degraded when a dependency mock fails.

### Gap Status

- Parity level: 75%
- Priority: P1
- Effort: S
- Owner area: backend/infra

## Subsystem 59: Security model

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/server/auth.ts`
- `external/opencode-source/packages/server/src/middleware/authorization.ts`
- `external/opencode-source/packages/opencode/src/permission/index.ts`
- `external/opencode-source/packages/opencode/src/provider/auth.ts`
- Responsibility: OpenCode has auth/authorization middleware, provider credential handling, permission rules, and location-scoped access.
- Important types/classes/functions: `V2Authorization`, `Auth`, `Provider auth`, `Permission rules`
- Runtime flow: OpenCode has auth/authorization middleware, provider credential handling, permission rules, and location-scoped access.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `backend/app/core/security.py`
- `backend/app/permissions/policy.py`
- `backend/app/core/config.py`
- `backend/app/db/models.py`
- Current status: PARTIAL
- OpenCode has what: OpenCode has auth/authorization middleware, provider credential handling, permission rules, and location-scoped access.
- Our Python platform has what: Python has TenantContext bootstrap, multi-tenant fields, permission policy, CORS config, and error handlers but no real auth.
- Current behavior: Python has TenantContext bootstrap, multi-tenant fields, permission policy, CORS config, and error handlers but no real auth.
- What is missing:
  - No authentication
  - No authorization checks on every resource
  - No RLS
  - No secret redaction
  - No CSRF/session model
  - No tool sandbox
- What is weak:
  - Bootstrap user creates single-user behavior
  - APIs are not protected by auth boundaries
- Production risk: Anyone with backend network access can create sessions and run ask-approved tools.
- Exact file to implement or polish next: `backend/app/core/security.py`
- Recommended action: Add local auth/token model and enforce tenant ownership in every route before services run.
- Test that proves it works: Add backend/tests/test_security.py proving unauthenticated access is rejected in production mode and cross-tenant IDs return 404/403.

### Gap Status

- Parity level: 35%
- Priority: P0
- Effort: XL
- Owner area: security/backend

## Subsystem 60: Production-readiness

### OpenCode Reference

Files inspected:
- `external/opencode-source/packages/opencode/src/session/processor.ts`
- `external/opencode-source/packages/opencode/src/server/server.ts`
- `external/opencode-source/packages/opencode/src/storage/schema.ts`
- `external/opencode-source/packages/core/test/session-runner.test.ts`
- Responsibility: OpenCode is a mature local agent runtime with tests, rich UI/CLI/TUI, provider/tool/plugin/session systems, and established architecture.
- Important types/classes/functions: `SessionProcessor`, `ToolRegistry`, `Permission.Service`, `Provider.Service`
- Runtime flow: OpenCode is a mature local agent runtime with tests, rich UI/CLI/TUI, provider/tool/plugin/session systems, and established architecture.
- Dependencies: inferred from the cited OpenCode files and their imported services/packages.

### Our Python Implementation

Files inspected:
- `README.md`
- `docker-compose.yml`
- `backend/app`
- `frontend/src`
- `scripts/smoke-test.sh`
- `docs/opencode-study`
- Current status: PARTIAL
- OpenCode has what: OpenCode is a mature local agent runtime with tests, rich UI/CLI/TUI, provider/tool/plugin/session systems, and established architecture.
- Our Python platform has what: Python is production-shaped with FastAPI, React, Docker dependencies, Postgres schema, agents/tools, permissions, events, Ollama, tests, and docs.
- Current behavior: Python is production-shaped with FastAPI, React, Docker dependencies, Postgres schema, agents/tools, permissions, events, Ollama, tests, and docs.
- What is missing:
  - Resumable queued runtime
  - Auth/authorization
  - Safe mutation tooling
  - Context/compaction
  - Complete permission lifecycle
  - Artifact/memory/plugin/MCP execution
- What is weak:
  - Architecture is production-shaped but not production-hardened
  - Several infrastructure services are health-checked but unused
- Production risk: Calling it production-ready now would overstate maturity and create operational/security risk.
- Exact file to implement or polish next: `docs/opencode-study/implementation-roadmap.md`
- Recommended action: Execute the P0 roadmap before adding new feature surface area.
- Test that proves it works: Full docker smoke test plus backend integration suite must prove health, auth, permission resume, tool audit, and chat/tool flows.

### Gap Status

- Parity level: 40%
- Priority: P0
- Effort: XL
- Owner area: platform

