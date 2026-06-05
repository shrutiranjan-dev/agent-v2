# Tool Registry Study

## Original Files Inspected

- `packages/opencode/src/tool/tool.ts`
- `packages/opencode/src/tool/registry.ts`
- `packages/opencode/src/tool/read.ts`
- `packages/opencode/src/tool/write.ts`
- `packages/opencode/src/tool/edit.ts`
- `packages/opencode/src/tool/grep.ts`
- `packages/opencode/src/tool/glob.ts`
- `packages/opencode/src/tool/shell.ts`
- `packages/opencode/src/tool/apply_patch.ts`
- `packages/opencode/src/tool/todo.ts`
- `packages/opencode/src/tool/question.ts`
- `packages/core/src/tool/registry.ts`
- `packages/llm/src/tool.ts`
- `packages/llm/src/tool-runtime.ts`

## Responsibility

The registry owns the advertised tool definitions and execution hooks. Tool leaves own their schemas and domain behavior. The runtime wraps them to validate arguments, request permissions, truncate output, publish metadata, and settle errors.

## Important Types / Classes / Functions

- `Tool.Def`: id, description, parameters, JSON schema, execute, validation formatter.
- `Tool.Context`: session ID, message ID, agent, abort signal, metadata callback, permission ask callback.
- `Tool.define`: wraps schema validation and output truncation.
- `ToolRegistry.tools`: builds model-visible tool definitions after provider/agent filtering.
- v2 `ToolRegistry.settle`: decodes input, authorizes, executes, validates output, and returns a typed settlement.

## Runtime Flow

1. Registry initializes built-ins and plugin tools.
2. For a provider turn, registry filters tools based on provider/model/agent rules.
3. Model emits tool call.
4. Runtime decodes JSON input.
5. Permission hook runs before side effects.
6. Tool executes and emits metadata/result.
7. Result is persisted and sent back into the model loop.

## Dependencies

OpenCode tools rely on FS utilities, ripgrep, LSP, formatters, patch parsing, event bridge, shell parser, plugin hooks, truncation, references, and session todo/question services.

## Python Equivalent Design

`backend/app/tools/base.py` defines `BaseTool`, typed input/output models, and `ToolContext`. `ToolRegistry` registers:

- `read.file`
- `write.file`
- `edit.file`
- `grep.search`
- `glob.search`
- `bash.run`
- `patch.apply`
- `todo.write`
- `question.ask`

`backend/app/runtime/tool_executor.py` centralizes:

- Pydantic input validation.
- Agent tool allow-list.
- Doom-loop guard.
- Permission evaluation.
- Tool call persistence.
- Audit logging.
- Event emission.
- Timeout handling.

## Implement Now

- Typed built-in tools.
- API list of available tools and schemas.
- Persistence and audit for every execution.
- Permission checks before side effects.

## Defer

- Plugin-contributed tools.
- MCP-contributed tools.
- LSP diagnostics and auto-format integration.
- Advanced shell AST path scanning.

## Risks And Assumptions

- Shell command parsing in OpenCode uses tree-sitter. The initial Python version uses conservative deny patterns and asks for shell execution by default; deeper command path authority checks can be added later.
- The target tool names are explicit dotted names rather than OpenCode's legacy names to avoid package identity confusion.
