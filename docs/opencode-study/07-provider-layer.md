# Provider Layer Study

## Original Files Inspected

- `packages/opencode/src/provider/provider.ts`
- `packages/opencode/src/provider/model-status.ts`
- `packages/opencode/src/provider/transform.ts`
- `packages/opencode/src/session/llm.ts`
- `packages/opencode/src/session/llm/native-runtime.ts`
- `packages/opencode/src/session/llm/native-request.ts`
- `packages/llm/src/provider.ts`
- `packages/llm/src/protocols/openai-chat.ts`
- `packages/llm/src/protocols/openai-responses.ts`
- `packages/llm/src/protocols/shared.ts`
- `specs/v2/provider-model.md`
- `specs/v2/provider-policy.md`

## Responsibility

OpenCode has a broad provider catalog with provider plugins, model metadata, SDK adapters, route selection, transforms, auth, and native LLM protocol adapters. It normalizes provider streams into common LLM events.

## Important Types / Classes / Functions

- `Provider.Service`: provider/model catalog, defaults, language model construction.
- `ProviderTransform`: message and provider option normalization.
- `LLM.Service.stream`: prepares model request and streams events.
- `LLMNativeRuntime.stream`: converts prepared session data into `@opencode-ai/llm` requests when supported.
- `ProviderV2`, `ModelV2`: provider/model identity and catalog structures.

## Runtime Flow

1. Resolve selected model and provider.
2. Load auth and provider options.
3. Normalize system/messages/tools.
4. Stream request through native runtime if supported; otherwise AI SDK.
5. Emit normalized text, reasoning, tool call, tool result, usage, and provider error events.

## Dependencies

OpenCode supports many cloud providers. The target intentionally supports only local Ollama in the first implementation.

## Python Equivalent Design

`backend/app/providers/ollama.py` wraps Ollama's local HTTP API:

- `GET /api/tags` for model list.
- `POST /api/generate` for text generation.
- `POST /api/pull` for model pull.
- Health check against `/api/tags`.

The provider layer never includes OpenAI, Anthropic, or cloud providers in this implementation.

## Implement Now

- Ollama endpoint config via env, defaulting to `http://ollama:11434`.
- Model list endpoint.
- Model pull endpoint.
- Generate endpoint used by agent runner.
- Model call persistence.

## Defer

- Streaming token-by-token UI rendering.
- Embeddings.
- Provider routing beyond Ollama.
- Provider policy beyond local-only enforcement.

## Risks And Assumptions

- Ollama's `/api/generate` returns text, not structured function calls. The target therefore prompts for strict JSON and validates it locally.
- Docker Compose includes an Ollama service, while `.env` can override to host Ollama.
