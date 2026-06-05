# UI Client Architecture Study

## Original Files Inspected

- `packages/app/src/app.tsx`
- `packages/app/src/context/server-sdk.tsx`
- `packages/app/src/context/server-sync.tsx`
- `packages/app/src/context/global-sync/event-reducer.ts`
- `packages/app/src/context/permission.tsx`
- `packages/app/src/context/models.tsx`
- `packages/app/src/pages/session.tsx`
- `packages/app/src/pages/session/message-timeline.tsx`
- `packages/app/src/components/session/session-header.tsx`
- `packages/ui/src/v2/components/*`

## Responsibility

The UI is an operational client over server state. It maintains session lists, message timelines, permissions, model/provider state, and live event sync. It renders tool calls and diffs as first-class conversation events rather than plain text.

## Important Types / Classes / Functions

- `PermissionProvider`: listens for `permission.asked` events and can auto-respond.
- `server-sync` and `global-sync`: bootstrap server state and reduce events into local stores.
- `message-timeline`: virtualized session timeline with message/tool/diff rows.
- UI primitives for buttons, tabs, dialogs, accordions, text inputs, and tool cards.

## Runtime Flow

1. Client bootstraps sessions, config, models, permissions, and server status.
2. Live event stream updates local stores.
3. Session view shows messages, parts, tools, permissions, and status.
4. Permission prompts can be approved or rejected from UI.
5. Model and server state remain visible.

## Dependencies

OpenCode uses SolidJS and a generated SDK. The target uses React, TypeScript, Vite, direct REST calls, and WebSocket events.

## Python Equivalent Design

The first React shell includes dashboard pages:

- Sessions
- Session detail/chat
- Agents
- Tools
- Permissions
- Model/Ollama status
- Artifacts
- System events

The UI is intentionally work-focused: dense, scan-friendly, and built around operational state.

## Implement Now

- Vite React app.
- API client wrapper.
- WebSocket hook for session events.
- Permission approve/deny controls.
- Dashboard navigation and core pages.

## Defer

- Virtualized long timelines.
- Rich diff rendering.
- File tree and terminal panels.
- UI auto-accept rules.

## Risks And Assumptions

- The target UI should not mimic OpenCode's brand or visual identity. It uses its own layout, palette, names, and interaction language.
