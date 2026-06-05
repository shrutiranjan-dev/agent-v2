# Python Port Map

## Original Files Inspected

This map synthesizes observations from:

- `packages/opencode/src/agent/agent.ts`
- `packages/opencode/src/tool/*.ts`
- `packages/opencode/src/permission/*.ts`
- `packages/opencode/src/session/*.ts`
- `packages/core/src/session/runner/llm.ts`
- `packages/core/src/tool/registry.ts`
- `packages/opencode/src/provider/*.ts`
- `packages/opencode/src/server/routes/instance/httpapi/**/*.ts`
- `packages/app/src/context/**/*.tsx`
- `packages/opencode/src/plugin/*.ts`
- `packages/opencode/src/mcp/*.ts`

## Subsystem Mapping

| OpenCode subsystem | Python subsystem | Implement now | Defer |
| --- | --- | --- | --- |
| Agent service | `backend/app/agents` | Native catalog, agent API, selected agent per run | Dynamic generation and user config |
| Tool registry | `backend/app/tools`, `backend/app/runtime/tool_executor.py` | Native tools, schema validation, audit, permission checks | Plugin/MCP tools, LSP integration |
| Permission engine | `backend/app/permissions` | allow/ask/deny, pending requests, destructive shell deny | saved approvals and auto-accept |
| Session runtime | `backend/app/runtime` | sessions, messages, runs, JSON protocol loop, events | durable inbox and context epochs |
| Provider layer | `backend/app/providers` | Ollama-only list/pull/generate/health | cloud providers, embeddings |
| Server API | `backend/app/api` | FastAPI routes and WebSocket | generated SDK |
| UI client | `frontend/src` | React dashboard shell | rich diff/file/terminal panels |
| Storage | `backend/app/db` | PostgreSQL schema and Alembic migration | advanced projections |
| Memory | `backend/app/memory` | client boundaries and schema | retrieval orchestration |
| Artifacts | `backend/app/artifacts` | metadata table and MinIO health | upload/download UI polish |
| Analytics | `backend/app/analytics` | ClickHouse health and event writer boundary | full analytics dashboards |
| Queue/cache | `backend/app/queue` | Redis health/client boundary | distributed run ownership |
| Plugins | `backend/app/plugins` | schema boundary | execution sandbox |
| MCP | `backend/app/mcp` | schema boundary | tool/resource execution |

## Runtime Flow In Python

1. `POST /sessions` creates tenant/project/workspace-safe session rows.
2. `POST /sessions/{id}/messages` records a user message and creates an `agent_runs` row.
3. `AgentRunner` resolves agent and model.
4. `OllamaProvider` generates strict JSON.
5. Runtime parses assistant response.
6. Final responses become assistant messages.
7. Tool calls are validated by `ToolRegistry`.
8. `ToolExecutor` checks loop guard and permissions.
9. Allowed tools run and persist results.
10. Ask tools create `permission_requests`, emit WebSocket events, and pause the run.
11. Denied tools fail with audit/system events.
12. Loop continues until final, max steps, invalid JSON failure, permission wait, or guard block.

## What To Implement Now

- Production skeleton and Docker Compose.
- PostgreSQL/pgvector migration with required tables.
- Health/dependency API.
- Agent/tool/permission/session/model routes.
- React operational dashboard.
- Smoke test script.

## What To Defer

- Full OpenCode parity for contextual file references, shell AST scanning, model-specific message transforms, rich UI timeline virtualization, plugin execution, and MCP runtime.

## Risks And Assumptions

- Architecture parity does not imply identical API names or UI design.
- Local-only model behavior is less reliable for tool calls than provider-native function calling; strict JSON validation and bounded repair are mandatory.
- The first implementation is production-shaped, not feature-complete against every OpenCode subsystem.
