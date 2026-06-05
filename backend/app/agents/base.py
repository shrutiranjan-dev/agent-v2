from pydantic import BaseModel, ConfigDict, Field


class ModelConfig(BaseModel):
    provider: str = "ollama"
    model: str
    supports_json_protocol: bool = True
    context_window: int | None = None
    max_output_tokens: int | None = None


class AgentDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    mode: str = Field(pattern="^(primary|subagent|all)$")
    llm: ModelConfig = Field(alias="model_config")
    system_prompt: str
    allowed_tools: list[str]
    permission_profile: str
    requires_json_protocol: bool = True
    max_steps: int = Field(default=12, ge=1, le=50)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    hidden: bool = False
