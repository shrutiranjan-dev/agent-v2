# Plugin And MCP System Study

## Original Files Inspected

- `packages/opencode/src/plugin/index.ts`
- `packages/opencode/src/plugin/loader.ts`
- `packages/opencode/src/plugin/shared.ts`
- `packages/plugin/src/index.ts`
- `packages/plugin/src/tool.ts`
- `packages/opencode/src/mcp/index.ts`
- `packages/opencode/src/mcp/auth.ts`
- `packages/opencode/src/mcp/oauth-provider.ts`
- `packages/opencode/src/mcp/oauth-callback.ts`
- `specs/v2/catalog-config-plugin-lifecycle.md`
- `specs/v2/config.md`

## Responsibility

Plugins extend config, providers, tools, shell env, auth flows, and workspace behavior. MCP connects local or remote MCP servers, lists tools/resources/prompts, converts MCP tools to model-visible tools, and handles OAuth states.

## Important Types / Classes / Functions

- `Plugin.Service.trigger/list/init`
- `PluginLoader.resolve/load/loadExternal`
- `PluginInput`, `Hooks`, `ToolDefinition` from `packages/plugin`
- `MCP.Service.status/tools/prompts/resources/add/connect/disconnect/readResource`
- MCP status union: connected, disabled, failed, needs auth, needs client registration.

## Runtime Flow

1. Config identifies plugin origins and MCP servers.
2. Loader resolves install target and entry point.
3. Compatibility is checked.
4. Plugin module is imported and hook object registered.
5. Hooks are triggered during config, tool definition, shell env, or other lifecycle events.
6. MCP clients connect and expose external tools/resources/prompts.

## Dependencies

OpenCode relies on dynamic module loading, npm/file plugin resolution, MCP TypeScript SDK, OAuth helpers, child process transports, and plugin hook contracts.

## Python Equivalent Design

Initial Python surfaces:

- `backend/app/plugins/loader.py`: DB-backed plugin metadata and disabled registry placeholder.
- `backend/app/plugins/hooks.py`: typed no-op hook dispatcher with stable names.
- `backend/app/mcp/client.py` and `registry.py`: schema and persistence boundaries for future MCP servers.

No MCP tool execution is implemented in the first slice because the user explicitly says MCP support later.

## Implement Now

- `plugins` and `mcp_servers` database tables.
- Route/API visibility via system metadata later.
- Document future plugin/MCP boundaries.

## Defer

- Dynamic plugin loading.
- MCP transport execution.
- OAuth callback server.
- MCP tools in the runtime tool registry.

## Risks And Assumptions

- Python plugin execution needs separate sandboxing and trust boundaries; do not port dynamic TypeScript plugin behavior blindly.
- MCP servers can execute arbitrary tools, so they must enter through the same permission/audit/loop-guard executor as native tools.
