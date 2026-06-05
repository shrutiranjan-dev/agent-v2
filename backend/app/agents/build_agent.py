from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.agents.prompts import BUILD_SYSTEM_PROMPT


def build_agent(model: ModelConfig, allowed_tools: list[str]) -> AgentDefinition:
    return AgentDefinition(
        id="build",
        name="Build",
        description="Default implementation agent for local coding and operational work.",
        mode="primary",
        model_config=model,
        system_prompt=BUILD_SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        permission_profile="default",
        max_steps=16,
        temperature=0.2,
        top_p=0.9,
    )
