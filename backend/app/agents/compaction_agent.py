from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.agents.prompts import COMPACTION_SYSTEM_PROMPT


def compaction_agent(model: ModelConfig) -> AgentDefinition:
    return AgentDefinition(
        id="compaction",
        name="Compaction",
        description="Hidden internal context compaction agent.",
        mode="primary",
        model_config=model,
        system_prompt=COMPACTION_SYSTEM_PROMPT,
        allowed_tools=[],
        permission_profile="none",
        max_steps=3,
        temperature=0.1,
        top_p=0.85,
        hidden=True,
    )
