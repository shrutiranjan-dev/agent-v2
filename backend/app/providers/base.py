from typing import Protocol

from pydantic import BaseModel, Field


class ModelCapability(BaseModel):
    name: str
    provider: str = "ollama"
    supports_json_protocol: bool = True
    supports_tools_native: bool = False
    context_window: int = 8192
    recommended_for: list[str] = Field(default_factory=list)
    max_output_tokens: int = 2048
    enabled: bool = True


class ModelProvider(Protocol):
    async def health(self) -> dict: ...

    async def list_models(self) -> list[dict]: ...

    async def pull_model(self, model: str) -> dict: ...

    async def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float,
        top_p: float,
    ) -> dict: ...

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        top_p: float,
    ) -> dict: ...

    async def embed(self, *, model: str, input_text: str) -> dict: ...
