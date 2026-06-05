# Session And Message Runtime Study

## Original Files Inspected

- `packages/opencode/src/session/session.ts`
- `packages/opencode/src/session/message.ts`
- `packages/opencode/src/session/message-v2.ts`
- `packages/opencode/src/session/prompt.ts`
- `packages/opencode/src/session/processor.ts`
- `packages/opencode/src/session/run-state.ts`
- `packages/core/src/session/runner/llm.ts`
- `packages/core/src/session/input.ts`
- `packages/core/src/session/store.ts`
- `packages/core/src/session/event.ts`
- `specs/v2/session.md`

## Responsibility

Sessions group durable conversation history, selected agent/model, tool calls, events, status, and context. The newer v2 direction separates prompt admission from execution and uses durable events/projections.

## Important Types / Classes / Functions

- `Session.Info`: ID, project/workspace, directory, parent, title, agent, model, tokens, permissions, timestamps.
- `Message.Info`: user/assistant role, parts, metadata, tool invocation parts.
- `SessionPrompt.prompt/loop`: legacy monolithic prompt and tool loop.
- `SessionRunner.run`: v2 local continuation with max steps, provider turns, tool settlement, and replayable events.
- `SessionInput`: durable inbox for prompt admission and execution wakeups.

## Runtime Flow

1. Create session.
2. Admit user message.
3. Resolve selected agent and model.
4. Build model context from durable message history.
5. Execute one provider turn.
6. Persist assistant text or tool calls.
7. Execute authorized local tools.
8. Persist results and continue until final response, max steps, or blocked state.

## Dependencies

OpenCode depends on storage, event projection, provider catalog, system context registry, tool registry, permission engine, and UI/live event streams.

## Python Equivalent Design

`backend/app/runtime` provides:

- `session_service.py`: creates/list/gets sessions with organization/project/workspace boundaries.
- `message_service.py`: persists user, assistant, and tool messages.
- `agent_runner.py`: strict JSON protocol loop for local Ollama responses.
- `tool_executor.py`: central settlement path.
- `loop_guard.py`: repeated identical tool-call protection.
- `event_bus.py`: persisted events plus WebSocket fan-out.

## Implement Now

- Session creation/list/get.
- User message admission.
- Agent run persistence.
- Strict JSON assistant protocol.
- One repair attempt for invalid JSON.
- Max-step and doom-loop guard.
- WebSocket events.

## Defer

- Full durable inbox with steer/queue semantics.
- Context epochs.
- Automatic summarization/compaction under context pressure.
- Multi-node ownership and crash recovery.

## Risks And Assumptions

- Local Ollama models may not reliably follow function-calling schemas, so the target uses an explicit JSON protocol in the system prompt.
- Invalid JSON repair is bounded to one retry to avoid unbounded loops.
