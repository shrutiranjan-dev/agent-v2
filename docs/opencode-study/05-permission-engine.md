# Permission Engine Study

## Original Files Inspected

- `packages/opencode/src/permission/index.ts`
- `packages/opencode/src/permission/evaluate.ts`
- `packages/opencode/src/permission/arity.ts`
- `packages/core/src/permission/schema.ts`
- `packages/core/src/permission/saved.ts`
- `packages/core/src/permission/sql.ts`
- `packages/server/src/handlers/v2/permission.ts`
- `packages/app/src/context/permission.tsx`

## Responsibility

The permission engine evaluates ordered rules and coordinates interactive approvals. It supports `allow`, `ask`, and `deny`, publishes pending permission events, and records replies. OpenCode also supports persistent approvals and auto-respond behavior in the UI.

## Important Types / Classes / Functions

- `Permission.evaluate(permission, pattern, ...rulesets)`: last matching wildcard rule wins; default is ask.
- `Permission.Service.ask`: evaluates all requested patterns, publishes `permission.asked`, waits for reply.
- `Permission.Service.reply`: resolves or rejects pending requests and can add session approvals.
- v2 `PermissionSaved`: project-level saved action/resource approvals.
- Bash arity map: converts shell commands into stable human-understandable approval prefixes.

## Runtime Flow

1. Tool calls `ctx.ask` with permission key, patterns, metadata, and always patterns.
2. Engine evaluates configured rules plus saved approvals.
3. Deny fails immediately.
4. Allow returns immediately.
5. Ask creates pending request and emits an event.
6. UI approves once/always or rejects.
7. Tool resumes or fails.

## Dependencies

OpenCode uses wildcard matching, Effect `Deferred`, event bridge, config rules, and UI persistent auto-accept state.

## Python Equivalent Design

`backend/app/permissions` implements:

- `PermissionRule`, `PermissionDecision`, and request models.
- `matcher.py` with wildcard matching.
- `policy.py` with default policy and destructive shell deny checks.
- `service.py` with DB-backed request creation, approval, denial, and audit.

The initial runtime pauses a run when permission is `ask` by creating `permission_requests`, emitting a WebSocket event, and marking the tool call/run as waiting. Approval endpoints persist the reply and emit follow-up events.

## Implement Now

- Default allow/ask/deny policy.
- External directory access asks.
- Destructive shell commands deny.
- Pending permission rows.
- Approve and deny endpoints.
- WebSocket permission prompt events.

## Defer

- Saved approvals with "always" pattern expansion.
- UI auto-accept rules.
- Full shell AST authority extraction.

## Risks And Assumptions

- The requirement says a tool waits or a run is paused. The first FastAPI implementation pauses the run and lets a later resume flow continue; it avoids holding HTTP requests indefinitely.
- Doom-loop protection is implemented separately as a guard but reports through the permission/audit/event path.
