# Server Architecture Study

## Original Files Inspected

- `packages/opencode/src/server/server.ts`
- `packages/opencode/src/server/routes/instance/httpapi/server.ts`
- `packages/opencode/src/server/routes/instance/httpapi/api.ts`
- `packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts`
- `packages/opencode/src/server/routes/instance/httpapi/handlers/permission.ts`
- `packages/opencode/src/server/routes/instance/httpapi/handlers/provider.ts`
- `packages/server/src/routes.ts`
- `packages/server/src/api.ts`
- `packages/server/src/handlers/v2/session.ts`
- `packages/server/src/handlers/v2/permission.ts`
- `packages/server/src/handlers/v2/event.ts`

## Responsibility

The server exposes typed HTTP groups over domain services. The legacy server provides instance-scoped routes for sessions, permissions, questions, provider data, files, PTY, MCP, and config. The newer v2 server wraps core services with typed handlers and maps domain errors to API errors.

## Important Types / Classes / Functions

- `InstanceHttpApi` groups in legacy HTTP API.
- `V2Api` in `packages/server/src/api.ts`.
- `sessionHandlers` for session list, prompt, compact, wait, and context.
- `permissionHandlers`, `sessionPermissionHandlers`, and `savedPermissionHandlers`.
- `eventHandlers`, which expose server-sent events.

## Runtime Flow

1. HTTP handler decodes payload/query via schema.
2. Handler resolves a location/session-specific service layer.
3. Service executes domain operation.
4. Known domain errors are converted to typed HTTP errors.
5. Event handlers stream a connected event followed by location-filtered domain events.

## Dependencies

OpenCode uses Effect HTTP APIs and generated SDK contracts. The target uses FastAPI routers, Pydantic request/response models, and SQLAlchemy-backed services.

## Python Equivalent Design

- `backend/app/api/routes_health.py`: `/health` and `/health/dependencies`.
- `routes_models.py`: Ollama model list/pull/status.
- `routes_agents.py`, `routes_tools.py`: native registries.
- `routes_sessions.py`, `routes_messages.py`: session creation, message admission, and run kickoff.
- `routes_permissions.py`: pending permission list and approve/deny.
- `routes_artifacts.py`, `routes_system_events.py`: operational metadata.
- `websocket.py`: `/ws/sessions/{id}` event stream.

## Implement Now

- FastAPI app with explicit route modules.
- Startup-safe dependency health checks.
- JSON error handling.
- CORS configured through env.
- WebSocket broadcast for session events and permission prompts.

## Defer

- Generated SDK.
- Server-side cursor pagination for every event stream.
- Multi-location routing.

## Risks And Assumptions

- OpenCode's current durable event stream is SSE-centric; this target uses WebSockets first because the requirement explicitly asks for WebSocket streaming.
- The first implementation keeps live WebSocket fan-out process-local while persisting events in PostgreSQL. Redis pub/sub can extend this to multi-process coordination without changing the API contract.
