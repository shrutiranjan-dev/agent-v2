from backend.app.core.config import get_settings
from backend.app.core.errors import NotFoundError
from backend.app.providers.base import ModelCapability
from backend.app.providers.ollama import ollama_provider


def get_provider(name: str = "ollama"):
    if name != "ollama":
        raise NotFoundError(f"Only local Ollama provider is supported in this implementation: {name}")
    return ollama_provider


def capability_for_model(name: str, *, recommended_for: list[str] | None = None) -> ModelCapability:
    settings = get_settings()
    return ModelCapability(
        name=name,
        provider="ollama",
        supports_json_protocol=name not in settings.ollama.non_json_models,
        supports_tools_native=False,
        context_window=settings.ollama.context_window,
        recommended_for=recommended_for or [],
        max_output_tokens=settings.ollama.max_output_tokens,
        enabled=name not in settings.ollama.disabled_models,
    )


def agent_configured_model(agent_id: str) -> str | None:
    settings = get_settings()
    return {
        "build": settings.ollama.build_model,
        "plan": settings.ollama.plan_model,
        "general": settings.ollama.general_model,
        "explore": settings.ollama.explore_model,
        "summary": settings.ollama.summary_model,
        "compaction": settings.ollama.compaction_model,
    }.get(agent_id)


def select_model_for_agent(agent_id: str, *, requires_json_protocol: bool = True) -> ModelCapability:
    settings = get_settings()
    candidates = [
        item
        for item in [agent_configured_model(agent_id), settings.ollama.default_model]
        if item
    ]
    for name in candidates:
        capability = capability_for_model(name, recommended_for=[agent_id])
        if not capability.enabled:
            continue
        if requires_json_protocol and not capability.supports_json_protocol:
            continue
        return capability
    raise NotFoundError(
        f"No enabled Ollama model is available for agent {agent_id} "
        f"with requires_json_protocol={requires_json_protocol}."
    )
