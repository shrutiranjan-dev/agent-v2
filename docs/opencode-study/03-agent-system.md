# Agent System Study

## Original Files Inspected

- `packages/opencode/src/agent/agent.ts`
- `packages/opencode/src/agent/prompt/explore.txt`
- `packages/opencode/src/agent/prompt/summary.txt`
- `packages/opencode/src/agent/prompt/compaction.txt`
- `packages/opencode/src/agent/subagent-permissions.ts`
- `specs/v2/config.md`

## Responsibility

Agents are named runtime profiles. They combine discoverability metadata, mode, model options, system prompt content, step budget, visibility, and permission rules. They do not own the full execution loop; the session runner does.

## Important Types / Classes / Functions

- `Agent.Info`: name, description, mode, native, hidden, topP, temperature, color, permission, model, variant, prompt, options, steps.
- `Agent.Service.get/list/defaultInfo/defaultAgent/generate`.
- Built-in agents: `build`, `plan`, `general`, `explore`, `compaction`, `title`, `summary`.

## Runtime Flow

1. Load default permission rules and user config.
2. Build native agent map.
3. Merge user overrides and custom agents.
4. Default visible primary agent is selected.
5. Runner resolves selected agent for prompts and permission evaluation.

## Dependencies

The OpenCode agent service depends on config, auth, provider catalog, skills, plugins, and permission conversion.

## Python Equivalent Design

`backend/app/agents/registry.py` exposes a deterministic native catalog:

- `build`: default implementation agent.
- `plan`: planning agent with write/edit/bash denied unless explicitly allowed later.
- `general`: broad multi-step agent.
- `explore`: read/search-oriented code exploration agent.
- `summary`: hidden internal summarizer.
- `compaction`: hidden internal context compactor.

Each agent has `id`, `name`, `description`, `mode`, `model_config`, `system_prompt`, `allowed_tools`, `permission_profile`, `max_steps`, `temperature`, `top_p`, and `hidden`.

## Implement Now

- Native catalog with no OpenCode branding.
- API listing agents.
- Agent selection in session message endpoint.
- Agent max-step guard.

## Defer

- Dynamic agent generation.
- User-authored agent config files.
- Agent-specific provider variants beyond local Ollama model selection.

## Risks And Assumptions

- OpenCode uses `title` as a hidden agent; the user requested `summary` and `compaction`, not title, so the initial target does not include title.
- The target uses explicit `allowed_tools` plus permission profiles to simplify first-run reasoning.
