import respx
from fastapi.testclient import TestClient
from httpx import Response

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.providers.router import select_model_for_agent


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def test_plan_agent_selects_configured_plan_model(monkeypatch) -> None:
    monkeypatch.setenv("AP_OLLAMA_PLAN_MODEL", "plan-model:latest")
    reset_settings_cache()
    try:
        capability = select_model_for_agent("plan")
        assert capability.name == "plan-model:latest"
        assert capability.recommended_for == ["plan"]
    finally:
        reset_settings_cache()


def test_disabled_agent_model_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("AP_DEFAULT_OLLAMA_MODEL", "fallback:latest")
    monkeypatch.setenv("AP_OLLAMA_PLAN_MODEL", "disabled:latest")
    monkeypatch.setenv("AP_OLLAMA_DISABLED_MODELS", "disabled:latest")
    reset_settings_cache()
    try:
        capability = select_model_for_agent("plan")
        assert capability.name == "fallback:latest"
        assert capability.enabled
    finally:
        reset_settings_cache()


def test_non_json_model_is_rejected_for_tool_call_agent(monkeypatch) -> None:
    monkeypatch.setenv("AP_DEFAULT_OLLAMA_MODEL", "chatty:latest")
    monkeypatch.setenv("AP_OLLAMA_NON_JSON_MODELS", "chatty:latest")
    reset_settings_cache()
    try:
        try:
            select_model_for_agent("build", requires_json_protocol=True)
        except Exception as exc:
            assert "requires_json_protocol=True" in str(exc)
        else:
            raise AssertionError("Expected non-JSON model to be rejected")
    finally:
        reset_settings_cache()


@respx.mock
def test_models_endpoint_includes_capability_metadata() -> None:
    respx.get("http://host.docker.internal:11434/api/tags").mock(
        return_value=Response(200, json={"models": [{"name": "qwen2.5:latest"}]})
    )
    client = TestClient(app)

    response = client.get("/models")

    assert response.status_code == 200
    model = response.json()["models"][0]
    assert model["name"] == "qwen2.5:latest"
    assert model["capabilities"]["provider"] == "ollama"
    assert "supports_json_protocol" in model["capabilities"]
