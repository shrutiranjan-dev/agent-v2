from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.agents.prompts import EXPLORE_SYSTEM_PROMPT


def explore_agent(model: ModelConfig, allowed_tools: list[str]) -> AgentDefinition:
    return AgentDefinition(
        id="explore",
        name="Explore",
        description="Fast read/search-oriented subagent for codebase exploration.",
        mode="subagent",
        model_config=model,
        system_prompt=EXPLORE_SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        permission_profile="readonly",
        max_steps=8,
        temperature=0.1,
        top_p=0.85,
    )
