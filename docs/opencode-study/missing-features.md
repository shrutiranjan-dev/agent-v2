# Missing Features

# P0 Missing

Critical features blocking production parity.

## Configuration system
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/opencode/src/config/config.ts`, `external/opencode-source/packages/opencode/src/config/agent.ts`, `external/opencode-source/packages/opencode/src/config/plugin.ts`
- Python file to implement or polish next: `backend/app/core/config.py`
- Missing behavior:
  - No persisted or file-based agent/tool/permission config
  - No production validation for default secrets
  - No per-organization or per-workspace overrides
- Acceptance test: Add backend/tests/test_config.py proving production mode rejects default secrets and loads workspace-specific permission defaults.

## Session model
- Status: PARTIAL, parity 65%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/session.ts`, `external/opencode-source/packages/opencode/src/session/schema.ts`, `external/opencode-source/packages/core/src/session/sql.ts`
- Python file to implement or polish next: `backend/app/db/models.py`
- Missing behavior:
  - No parent/fork fields
  - No token/cost summary fields
  - No archive/share/revert lifecycle
  - No explicit directory/path field
- Acceptance test: Extend backend/tests/test_sessions.py to prove tenant-isolated detail and persisted model/cost/status transitions.

## Message model
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/message.ts`, `external/opencode-source/packages/opencode/src/session/message-v2.ts`, `external/opencode-source/packages/opencode/src/session/schema.ts`
- Python file to implement or polish next: `backend/app/runtime/message_service.py`
- Missing behavior:
  - No typed message part tables
  - No streaming reasoning/tool part updates
  - No attachments/file references
  - No pagination/windowing
- Acceptance test: Add backend/tests/test_messages.py proving typed parts round-trip and invalid payloads are rejected.

## Agent run model
- Status: PARTIAL, parity 60%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/processor.ts`, `external/opencode-source/packages/opencode/src/session/status.ts`, `external/opencode-source/packages/core/test/session-runner.test.ts`
- Python file to implement or polish next: `backend/app/runtime/agent_runner.py`
- Missing behavior:
  - No durable resumable processor state
  - No cancellation/abort ownership
  - No snapshot/context version
  - No background queue
- Acceptance test: Add backend/tests/test_agent_run_resume.py proving a waiting_permission run continues after approve.

## Tool call model
- Status: PARTIAL, parity 65%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/processor.ts`, `external/opencode-source/packages/opencode/src/tool/tool.ts`, `external/opencode-source/packages/llm/src/tool-runtime.ts`
- Python file to implement or polish next: `backend/app/db/models.py`
- Missing behavior:
  - No raw streamed input tracking
  - No attachment linkage enforcement
  - No normalized tool output table
  - No retry/correction metadata
- Acceptance test: Extend backend/tests/test_tool_call_persistence.py proving permission_request_id references a row and approved calls complete.

## Event system
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/opencode/src/server/event.ts`, `external/opencode-source/packages/opencode/src/event-v2-bridge.ts`, `external/opencode-source/packages/server/src/groups/v2/event.ts`
- Python file to implement or polish next: `backend/app/runtime/event_bus.py`
- Missing behavior:
  - No Pydantic schema per event type
  - No Redis pub/sub cross-process broadcast
  - No replay cursor
  - No location/workspace subscription filter
- Acceptance test: Add backend/tests/test_event_bus.py proving event payload validation and replay after reconnect.

## WebSocket/realtime events
- Status: PARTIAL, parity 60%
- OpenCode reference: `external/opencode-source/packages/server/src/groups/v2/event.ts`, `external/opencode-source/packages/server/src/handlers/v2/event.ts`, `external/opencode-source/packages/app/src/context/server-sync.tsx`
- Python file to implement or polish next: `frontend/src/stores/eventStore.ts`
- Missing behavior:
  - No heartbeat/ping protocol
  - No reconnect replay cursor
  - No global WebSocket route
  - No typed frontend reducer
- Acceptance test: Add frontend event reducer test and backend /sessions/{id}/events replay ordering test.

## Agent prompts/system instructions
- Status: PARTIAL, parity 40%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/prompt/default.txt`, `external/opencode-source/packages/opencode/src/session/prompt/plan.txt`, `external/opencode-source/packages/opencode/src/session/prompt/build-switch.txt`
- Python file to implement or polish next: `backend/app/runtime/context_builder.py`
- Missing behavior:
  - No prompt composition pipeline
  - No provider/model-specific prompt variants
  - No max-step or permission reminder injection
  - No prompt version snapshot on model calls
- Acceptance test: Add backend/tests/test_context_builder.py proving prompts contain role, allowed tools, protocol examples, and max-step guardrails.

## Agent runtime loop
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/processor.ts`, `external/opencode-source/packages/opencode/src/session/llm.ts`, `external/opencode-source/packages/opencode/src/session/llm/ai-sdk.ts`
- Python file to implement or polish next: `backend/app/runtime/agent_runner.py`
- Missing behavior:
  - No streaming token/tool events
  - No resume after permission approval
  - No cancellation
  - No background ownership/locks
  - No compaction trigger
- Acceptance test: Add backend/tests/test_agent_runtime_state_machine.py covering final, tool, permission-wait/resume, max-step, and invalid JSON paths.

## Agent context building
- Status: PARTIAL, parity 30%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/instruction.ts`, `external/opencode-source/packages/opencode/src/session/system.ts`, `external/opencode-source/packages/core/test/system-context.test.ts`
- Python file to implement or polish next: `backend/app/runtime/context_builder.py`
- Missing behavior:
  - No dedicated context builder
  - No token budget/windowing
  - No workspace summary
  - No memory retrieval
  - No active file/artifact references
- Acceptance test: Add backend/tests/test_context_builder.py proving long sessions are windowed and summaries/tool outputs are deterministic.

## File write tool
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/write.ts`, `external/opencode-source/packages/core/test/tool-write.test.ts`, `external/opencode-source/packages/core/test/file-mutation.test.ts`
- Python file to implement or polish next: `backend/app/tools/write.py`
- Missing behavior:
  - No atomic write
  - No snapshot/diff before write
  - No secret-file protection
  - No resume-after-approval execution
- Acceptance test: Add backend/tests/test_write_tool.py proving ask flow, atomic write, and denied secret overwrite.

## Edit/patch tool
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/edit.ts`, `external/opencode-source/packages/opencode/src/tool/apply_patch.ts`, `external/opencode-source/packages/opencode/src/patch/index.ts`
- Python file to implement or polish next: `backend/app/tools/patch.py`
- Missing behavior:
  - No robust unified diff parser
  - No multi-hunk context matching
  - No rollback/snapshot
  - No formatting/conflict output
- Acceptance test: Add backend/tests/test_patch_tool.py with add/update/delete, multi-hunk, context mismatch, and rollback cases.

## Bash/shell tool
- Status: PARTIAL, parity 40%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/shell.ts`, `external/opencode-source/packages/opencode/src/shell/shell.ts`, `external/opencode-source/packages/core/test/tool-bash.test.ts`
- Python file to implement or polish next: `backend/app/tools/bash.py`
- Missing behavior:
  - No shell sandbox
  - No command AST/prefix allow rules
  - No environment scrub
  - No interactive process control
  - No exit-code failure policy
- Acceptance test: Add backend/tests/test_bash_tool.py proving destructive deny, external cwd ask, env scrub, and nonzero exit failure.

## Permission engine
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/opencode/src/permission/index.ts`, `external/opencode-source/packages/opencode/src/permission/evaluate.ts`, `external/opencode-source/packages/core/test/permission.test.ts`
- Python file to implement or polish next: `backend/app/permissions/service.py`
- Missing behavior:
  - No wildcard ruleset used by policy
  - No once/always saved approvals
  - No runtime wait/resume after approval
  - No session-wide reject cascade
- Acceptance test: Add backend/tests/test_permission_resume.py proving write.file waits, approve resumes, deny fails, and always approval skips future prompts.

## Permission request/approval flow
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/server/src/groups/v2/permission.ts`, `external/opencode-source/packages/opencode/src/permission/index.ts`, `external/opencode-source/packages/opencode/src/cli/cmd/run/permission.shared.ts`
- Python file to implement or polish next: `backend/app/api/routes_permissions.py`
- Missing behavior:
  - No once/always/reject semantics
  - No resume of ToolCall.waiting_permission
  - No stale prompt timeout handling
  - No strong ownership check on request
- Acceptance test: Add backend/tests/test_permissions_api.py proving approve moves tool_call and agent_run out of waiting_permission.

## Permission UI integration
- Status: PARTIAL, parity 50%
- OpenCode reference: `external/opencode-source/packages/app/src/context/permission.tsx`, `external/opencode-source/packages/app/src/context/permission-auto-respond.ts`, `external/opencode-source/packages/opencode/src/cli/cmd/run/footer.permission.tsx`
- Python file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Missing behavior:
  - No once/always choice
  - No auto-approve setting
  - No modal with tool input preview
  - No resumed output after approval
- Acceptance test: Add frontend test proving prompt appears from event and approve updates sidecar/tool status.

## Environment/secret file protection
- Status: MISSING, parity 15%
- OpenCode reference: `external/opencode-source/packages/opencode/src/env.ts`, `external/opencode-source/packages/opencode/src/auth/index.ts`, `external/opencode-source/packages/opencode/src/provider/auth.ts`
- Python file to implement or polish next: `backend/app/permissions/secret_policy.py`
- Missing behavior:
  - No ask/deny patterns for .env, keys, certs, SSH, tokens, or cloud credentials
  - No redaction in tool output/model_call request_json
  - No secret scanning before writes
- Acceptance test: Add backend/tests/test_secret_policy.py proving .env/private-key reads ask or deny and outputs are redacted.

## Audit logging
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/processor.ts`, `external/opencode-source/packages/opencode/src/permission/index.ts`, `external/opencode-source/packages/opencode/src/storage/schema.ts`
- Python file to implement or polish next: `backend/app/audit/service.py`
- Missing behavior:
  - No audit on model calls, session creation, message creation, artifact operations, or loop guard denial
  - No actor/IP propagation
  - No audit query API
- Acceptance test: Add backend/tests/test_audit_logs.py proving every tool permission decision and model call writes one redacted audit row.

## Session detail/chat UI
- Status: PARTIAL, parity 60%
- OpenCode reference: `external/opencode-source/packages/app/src/pages/session.tsx`, `external/opencode-source/packages/app/src/pages/session/message-timeline.tsx`, `external/opencode-source/packages/app/src/components/prompt-input.tsx`
- Python file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Missing behavior:
  - No streaming assistant text
  - No structured tool/reasoning/artifact rendering
  - No chat session persistence selector
  - No markdown/code rendering
- Acceptance test: Add frontend test proving /models populates dropdown and send payload includes model_name for new/existing chats.

## Permission prompt UI
- Status: PARTIAL, parity 50%
- OpenCode reference: `external/opencode-source/packages/app/src/context/permission.tsx`, `external/opencode-source/packages/opencode/src/cli/cmd/run/footer.permission.tsx`, `external/opencode-source/packages/app/src/context/permission-auto-respond.ts`
- Python file to implement or polish next: `frontend/src/components/PermissionPrompt.tsx`
- Missing behavior:
  - No input diff preview
  - No once/always controls
  - No auto-approve settings
  - No visual indication approval resumed or failed execution
- Acceptance test: Add frontend PermissionPrompt test covering approve, deny, duplicate-click disabled state, and risk preview.

## Testing coverage
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/core/test/session-runner.test.ts`, `external/opencode-source/packages/core/test/tool-read.test.ts`, `external/opencode-source/packages/core/test/tool-write.test.ts`
- Python file to implement or polish next: `backend/tests/test_permission_resume.py`
- Missing behavior:
  - No dependency integration tests
  - No frontend tests
  - No tool execution persistence tests
  - No permission approval/resume tests
  - No migration tests
- Acceptance test: The new tests plus dockerized smoke-test must pass before implementation work continues.

## Security model
- Status: PARTIAL, parity 35%
- OpenCode reference: `external/opencode-source/packages/opencode/src/server/auth.ts`, `external/opencode-source/packages/server/src/middleware/authorization.ts`, `external/opencode-source/packages/opencode/src/permission/index.ts`
- Python file to implement or polish next: `backend/app/core/security.py`
- Missing behavior:
  - No authentication
  - No authorization checks on every resource
  - No RLS
  - No secret redaction
  - No CSRF/session model
  - No tool sandbox
- Acceptance test: Add backend/tests/test_security.py proving unauthenticated access is rejected in production mode and cross-tenant IDs return 404/403.

## Production-readiness
- Status: PARTIAL, parity 40%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/processor.ts`, `external/opencode-source/packages/opencode/src/server/server.ts`, `external/opencode-source/packages/opencode/src/storage/schema.ts`
- Python file to implement or polish next: `docs/opencode-study/implementation-roadmap.md`
- Missing behavior:
  - Resumable queued runtime
  - Auth/authorization
  - Safe mutation tooling
  - Context/compaction
  - Complete permission lifecycle
  - Artifact/memory/plugin/MCP execution
- Acceptance test: Full docker smoke test plus backend integration suite must prove health, auth, permission resume, tool audit, and chat/tool flows.

# P1 Missing

Important features needed soon.

## Project/workspace structure
- Status: PARTIAL, parity 65%
- OpenCode reference: `external/opencode-source/package.json`, `external/opencode-source/pnpm-workspace.yaml`, `external/opencode-source/packages/opencode/src/project/project.ts`
- Python file to implement or polish next: `backend/app/api/routes_workspaces.py`
- Missing behavior:
  - No explicit project/workspace switching API
  - No workspace location resolver comparable to OpenCode location middleware
  - No generated client boundary between backend and frontend packages
- Acceptance test: Add backend/tests/test_workspaces.py proving session creation uses the requested workspace root and rejects cross-organization IDs.

## API route structure
- Status: PARTIAL, parity 60%
- OpenCode reference: `external/opencode-source/packages/server/src/api.ts`, `external/opencode-source/packages/server/src/groups/v2/session.ts`, `external/opencode-source/packages/server/src/groups/v2/message.ts`
- Python file to implement or polish next: `backend/app/api/__init__.py`
- Missing behavior:
  - No versioned /api/v1 surface
  - No provider/workspace/filesystem/command/skill/question reply route parity
  - No cursor pagination
- Acceptance test: Add backend/tests/test_api_contract.py validating route envelopes, tenant filtering, and OpenAPI paths.

## OpenAPI/schema generation
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/server/src/api.ts`, `external/opencode-source/packages/server/src/groups/v2/session.ts`, `external/opencode-source/packages/server/src/middleware/schema-error.ts`
- Python file to implement or polish next: `frontend/src/api/client.ts`
- Missing behavior:
  - No generated TypeScript client
  - No schema lint check in CI or smoke tests
  - No shared error schema across every route
- Acceptance test: Add scripts/check-openapi.sh and frontend build validation for generated types.

## Native agents
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/opencode/src/agent/agent.ts`, `external/opencode-source/packages/opencode/src/agent/prompt/explore.txt`, `external/opencode-source/packages/opencode/src/agent/prompt/summary.txt`
- Python file to implement or polish next: `backend/app/agents/prompts.py`
- Missing behavior:
  - No role-specific prompt files
  - No agent-to-agent task tool
  - No build/plan switching protocol
  - No summarization/compaction execution path
- Acceptance test: Add backend/tests/test_agent_permissions.py proving general/chat cannot mutate files unless configured.

## Compaction/summarization
- Status: MISSING, parity 10%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/compaction.ts`, `external/opencode-source/packages/opencode/src/session/summary.ts`, `external/opencode-source/packages/opencode/src/agent/prompt/summary.txt`
- Python file to implement or polish next: `backend/app/runtime/compaction_service.py`
- Missing behavior:
  - No compaction endpoint
  - No summary persistence
  - No overflow detector
  - No compacted context boundary
- Acceptance test: Add backend/tests/test_compaction.py proving compact creates summary metadata and later context uses it.

## Model provider abstraction
- Status: PARTIAL, parity 40%
- OpenCode reference: `external/opencode-source/packages/opencode/src/provider/provider.ts`, `external/opencode-source/packages/opencode/src/provider/model-status.ts`, `external/opencode-source/packages/llm/src/provider.ts`
- Python file to implement or polish next: `backend/app/providers/base.py`
- Missing behavior:
  - No provider interface enforcement in tests
  - No streaming API
  - No embeddings interface
  - No provider status persistence
- Acceptance test: Extend backend/tests/test_ollama_provider.py proving capability metadata and error normalization.

## Tool registry
- Status: PARTIAL, parity 65%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/registry.ts`, `external/opencode-source/packages/opencode/src/tool/tool.ts`, `external/opencode-source/packages/opencode/src/tool/schema.ts`
- Python file to implement or polish next: `backend/app/tools/registry.py`
- Missing behavior:
  - No plugin/MCP tool registration
  - No skill/task/LSP/web tools
  - No model-specific filtering
  - No disabled-tool calculation from permission rules
- Acceptance test: Extend backend/tests/test_tool_registry.py proving duplicate names are rejected and dynamic tools expose schemas safely.

## Todo tool
- Status: PARTIAL, parity 35%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/todo.ts`, `external/opencode-source/packages/opencode/src/session/todo.ts`, `external/opencode-source/packages/core/test/tool-todowrite.test.ts`
- Python file to implement or polish next: `backend/app/runtime/todo_service.py`
- Missing behavior:
  - No durable session todo state
  - No API to read current todos
  - No UI todo panel
  - No audit of todo transitions
- Acceptance test: Add backend/tests/test_todo_tool.py proving todo.write updates durable session todo state.

## Question/human input tool
- Status: PARTIAL, parity 30%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/question.ts`, `external/opencode-source/packages/opencode/src/question/index.ts`, `external/opencode-source/packages/server/src/groups/v2/question.ts`
- Python file to implement or polish next: `backend/app/runtime/question_service.py`
- Missing behavior:
  - No question_requests table
  - No question.requested event
  - No answer endpoint
  - No run pause/resume on answer
- Acceptance test: Add backend/tests/test_question_flow.py proving question.ask pauses and resumes with a user answer.

## Artifact storage
- Status: PARTIAL, parity 45%
- OpenCode reference: `external/opencode-source/packages/opencode/src/tool/truncate.ts`, `external/opencode-source/packages/opencode/src/tool/truncation-dir.ts`, `external/opencode-source/packages/core/test/tool-output-store.test.ts`
- Python file to implement or polish next: `backend/app/artifacts/artifact_service.py`
- Missing behavior:
  - No upload/download API
  - No presigned URLs
  - No ToolExecutor artifact persistence
  - No UI preview/download action
- Acceptance test: Add backend/tests/test_artifacts.py proving artifact upload, persistence, list, and download.

## Queue/worker runtime
- Status: PARTIAL, parity 25%
- OpenCode reference: `external/opencode-source/packages/opencode/src/background/job.ts`, `external/opencode-source/packages/opencode/src/session/processor.ts`, `external/opencode-source/packages/core/test/session-run-coordinator.test.ts`
- Python file to implement or polish next: `backend/app/queue/worker.py`
- Missing behavior:
  - No Redis queue
  - No worker process command
  - No distributed locks
  - No retry/dead-letter semantics
  - No cancellation
- Acceptance test: Add backend/tests/test_worker_runtime.py proving enqueue, worker execution, retry, and permission resume.

## Web UI dashboard
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/app/src/pages/layout.tsx`, `external/opencode-source/packages/app/src/pages/home.tsx`, `external/opencode-source/packages/app/src/pages/layout/sidebar-shell.tsx`
- Python file to implement or polish next: `frontend/src/pages/Dashboard.tsx`
- Missing behavior:
  - No project/workspace navigation
  - No settings dialogs
  - No file tree or diff view
  - No generated client/store architecture
- Acceptance test: Add frontend component tests proving each tab renders with mocked API data.

## Logs/events UI
- Status: PARTIAL, parity 55%
- OpenCode reference: `external/opencode-source/packages/app/src/components/status-popover.tsx`, `external/opencode-source/packages/app/src/components/titlebar-session-events.ts`, `external/opencode-source/packages/app/src/context/global-sync/event-reducer.ts`
- Python file to implement or polish next: `frontend/src/pages/EventsPage.tsx`
- Missing behavior:
  - No filtering by severity/type/session
  - No event detail payload expansion
  - No audit log UI
  - No pagination
- Acceptance test: Add frontend EventsPage test proving severity/type filters and payload detail toggle.

# P2 Missing

Useful but can wait.

## Memory/vector storage
- Status: PARTIAL, parity 25%
- OpenCode reference: `external/opencode-source/packages/opencode/src/session/summary.ts`, `external/opencode-source/packages/opencode/src/reference/reference.ts`, `external/opencode-source/packages/core/test/system-context.test.ts`
- Python file to implement or polish next: `backend/app/memory/memory_service.py`
- Missing behavior:
  - No embedding provider
  - No memory write/read API
  - No Qdrant collection management
  - No retrieval in context builder
- Acceptance test: Add backend/tests/test_memory_service.py proving memory insert, vector search mock, and context retrieval.

## Graph storage
- Status: PARTIAL, parity 25%
- OpenCode reference: `external/opencode-source/packages/opencode/src/reference/reference.ts`, `external/opencode-source/packages/core/test/project-reference.test.ts`, `external/opencode-source/packages/core/test/repository.test.ts`
- Python file to implement or polish next: `backend/app/memory/graph_store.py`
- Missing behavior:
  - No graph schema
  - No Cypher repository layer
  - No ingestion from file scans/tool calls
  - No agent context usage
- Acceptance test: Add backend/tests/test_graph_store.py proving health, upsert, and traversal with mocked Neo4j session.

## ClickHouse/event analytics
- Status: PARTIAL, parity 25%
- OpenCode reference: `external/opencode-source/packages/opencode/src/server/event.ts`, `external/opencode-source/packages/core/test/event.test.ts`
- Python file to implement or polish next: `backend/app/analytics/event_writer.py`
- Missing behavior:
  - No ClickHouse schema migration
  - No event writer invocation
  - No analytics API or dashboard
- Acceptance test: Add backend/tests/test_event_writer.py proving event_writer serializes SystemEvent to ClickHouse insert payload.

## Plugin system
- Status: MISSING, parity 15%
- OpenCode reference: `external/opencode-source/packages/opencode/src/plugin/index.ts`, `external/opencode-source/packages/opencode/src/plugin/loader.ts`, `external/opencode-source/packages/plugin/src/index.ts`
- Python file to implement or polish next: `backend/app/plugins/loader.py`
- Missing behavior:
  - No plugin manifest schema
  - No loader
  - No hook dispatch
  - No sandbox
  - No plugin tool registration
- Acceptance test: Add backend/tests/test_plugin_loader.py proving disabled plugins do not load and invalid manifests are rejected.

## MCP integration
- Status: MISSING, parity 10%
- OpenCode reference: `external/opencode-source/packages/opencode/src/mcp/index.ts`, `external/opencode-source/packages/opencode/src/mcp/auth.ts`, `external/opencode-source/packages/opencode/src/mcp/oauth-provider.ts`
- Python file to implement or polish next: `backend/app/mcp/client.py`
- Missing behavior:
  - No stdio/SSE/HTTP MCP client
  - No server lifecycle
  - No tool registration
  - No permission mapping
  - No UI management
- Acceptance test: Add backend/tests/test_mcp_registry.py with a fake MCP server exposing one permission-checked tool.

## CLI client
- Status: PARTIAL, parity 30%
- OpenCode reference: `external/opencode-source/packages/opencode/src/cli/bootstrap.ts`, `external/opencode-source/packages/opencode/src/cli/cmd/run.ts`, `external/opencode-source/packages/opencode/src/cli/cmd/session.ts`
- Python file to implement or polish next: `backend/app/cli.py`
- Missing behavior:
  - No chat/run command
  - No session list/detail command
  - No model list/pull command
  - No permission response command
  - No smoke/debug commands
- Acceptance test: Add backend/tests/test_cli.py using Typer CliRunner for serve config and models/session commands.

## Agent/tool management UI
- Status: PARTIAL, parity 35%
- OpenCode reference: `external/opencode-source/packages/app/src/components/dialog-settings.tsx`, `external/opencode-source/packages/app/src/components/settings-models.tsx`, `external/opencode-source/packages/app/src/utils/agent.ts`
- Python file to implement or polish next: `frontend/src/pages/AgentsPage.tsx`
- Missing behavior:
  - No create/edit/disable agent UI
  - No tool permission override UI
  - No plugin/MCP tool management
- Acceptance test: Add frontend tests proving detail drawers show allowed tools, permission profile, and JSON schema.

# P3 Missing

Optional/future.

