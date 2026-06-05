# Repository Structure Study

## Original Files Inspected

- `package.json`
- `packages/opencode/src/**`
- `packages/core/src/**`
- `packages/server/src/**`
- `packages/app/src/**`
- `packages/ui/src/**`
- `packages/plugin/src/**`
- `packages/llm/src/**`
- `specs/v2/session.md`
- `specs/v2/config.md`
- `specs/v2/provider-model.md`
- `specs/v2/provider-policy.md`

## Responsibility

OpenCode is a Bun/TypeScript monorepo. The visible product is split across:

- `packages/opencode`: legacy runtime, CLI/server integration, agents, tools, permissions, provider catalog, MCP, plugin loading, sessions.
- `packages/core`: newer v2 domain services, event-sourced session slices, location-scoped services, database schema and migrations.
- `packages/server`: generated/typed v2 HTTP API handlers over the core package.
- `packages/app`: SolidJS application shell for sessions, prompts, permissions, models, sync, and timeline rendering.
- `packages/ui`: reusable UI primitives, themes, message parts, diffs, controls.
- `packages/llm`: provider-neutral LLM request/event schemas, provider protocols, tool definition/runtime adapters.
- `packages/plugin`: plugin public API types.

## Important Types / Classes / Functions

- `Agent.Info`, `Agent.Service` in `packages/opencode/src/agent/agent.ts`
- `Tool.Def`, `Tool.Context`, `Tool.define` in `packages/opencode/src/tool/tool.ts`
- `ToolRegistry.Service` in both `packages/opencode/src/tool/registry.ts` and `packages/core/src/tool/registry.ts`
- `Permission.Service`, `Permission.evaluate` in `packages/opencode/src/permission/index.ts`
- `SessionPrompt.Service` in `packages/opencode/src/session/prompt.ts`
- `SessionRunner.Service` in `packages/core/src/session/runner/llm.ts`
- `LLM.Service` and native runtime adapters in `packages/opencode/src/session/llm.ts`
- `Provider.Service` in `packages/opencode/src/provider/provider.ts`
- `MCP.Service` in `packages/opencode/src/mcp/index.ts`
- `Plugin.Service` and `PluginLoader` in `packages/opencode/src/plugin/index.ts` and `loader.ts`

## Runtime Flow

The legacy runtime is service-oriented with Effect layers. The newer v2 direction moves state and APIs into smaller domain services:

1. API or UI admits session work.
2. Session service persists prompt/session state.
3. Runner resolves model, agent, tools, context, and permissions.
4. LLM stream produces text, reasoning, errors, or tool calls.
5. Tool registry validates, authorizes, executes, and settles tool calls.
6. Events update durable session projections and live UI streams.

## Dependencies

Core dependencies include Effect, Drizzle/SQLite, Bun, AI SDK, MCP SDK, tree-sitter shell parsers, SolidJS, and provider SDK packages. The target Python system replaces these with FastAPI, SQLAlchemy async, PostgreSQL/pgvector, Redis, Qdrant, Neo4j, MinIO, ClickHouse, Pydantic v2, and local Ollama.

## Python Equivalent Design

The target repo keeps equivalent boundaries but uses Python-native services:

- `backend/app/agents`: native agent catalog.
- `backend/app/tools`: typed tool registry.
- `backend/app/permissions`: ordered permission rules, pending requests, replies.
- `backend/app/runtime`: session/message services, agent runner, tool executor, event bus, loop guard.
- `backend/app/providers`: Ollama-only provider facade.
- `backend/app/db`: SQLAlchemy models and Alembic migrations.
- `frontend`: React/Vite operational web dashboard.

## Implement Now

- Production project skeleton.
- Database schema and migrations.
- Health and dependency checks.
- Native agent/tool registries.
- Initial permission engine and loop guard.
- Ollama provider endpoints.
- Web UI shell consuming FastAPI endpoints.

## Defer

- Full MCP execution.
- Full plugin sandboxing and installation.
- Multi-node run ownership.
- Full context epoch/source reconciliation.
- Advanced compaction and summarization policies.

## Risks And Assumptions

- OpenCode's source is evolving quickly; the pinned commit is the study baseline.
- Some v2 files are explicitly marked incomplete. This port adopts the architectural direction while implementing production storage from day one.
- The target avoids SQLite entirely, so event persistence and session projection are modeled directly in PostgreSQL rather than copied from Drizzle/SQLite.
