from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.agents.prompts import PLAN_SYSTEM_PROMPT


def plan_agent(model: ModelConfig, allowed_tools: list[str]) -> AgentDefinition:
    return AgentDefinition(
        id="plan",
        name="Plan",
        description="Planning agent that researches and proposes implementation steps without editing files.",
        mode="primary",
        model_config=model,
        system_prompt=PLAN_SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        permission_profile="readonly",
        max_steps=10,
        temperature=0.1,
        top_p=0.85,
    )
