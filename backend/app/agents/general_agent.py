from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.agents.prompts import GENERAL_SYSTEM_PROMPT


def general_agent(model: ModelConfig, allowed_tools: list[str]) -> AgentDefinition:
    return AgentDefinition(
        id="general",
        name="General",
        description="General-purpose agent for broad investigation and multi-step local tasks.",
        mode="subagent",
        model_config=model,
        system_prompt=GENERAL_SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        permission_profile="default",
        max_steps=12,
        temperature=0.25,
        top_p=0.9,
    )
