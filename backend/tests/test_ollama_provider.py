import pytest
import respx
from httpx import HTTPStatusError, Response

from backend.app.providers.ollama import OllamaProvider


@respx.mock
async def test_ollama_list_models() -> None:
    provider = OllamaProvider("http://ollama.test")
    respx.get("http://ollama.test/api/tags").mock(
        return_value=Response(
            200,
            json={
                "models": [
                    {"name": "qwen2.5:latest"},
                    {"name": "gemma4:31b-cloud", "remote_model": "gemma4:31b", "remote_host": "https://ollama.com:443"},
                ]
            },
        )
    )
    assert await provider.list_models() == [
        {"name": "qwen2.5:latest"},
        {"name": "gemma4:31b-cloud", "remote_model": "gemma4:31b", "remote_host": "https://ollama.com:443"},
    ]


@respx.mock
async def test_ollama_health_counts_all_ollama_models() -> None:
    provider = OllamaProvider("http://ollama.test")
    respx.get("http://ollama.test/api/tags").mock(
        return_value=Response(
            200,
            json={
                "models": [
                    {"name": "qwen2.5:latest"},
                    {"name": "gpt-oss:120b-cloud", "remote_model": "gpt-oss:120b"},
                    {"name": "deepseek-coder:6.7b"},
                ]
            },
        )
    )
    assert await provider.health() == {"status": "ok", "models": 3, "base_url": "http://ollama.test"}


@respx.mock
async def test_ollama_generate() -> None:
    provider = OllamaProvider("http://ollama.test")
    respx.post("http://ollama.test/api/generate").mock(
        return_value=Response(200, json={"response": '{"type":"final","content":"ok"}', "eval_count": 3})
    )
    result = await provider.generate(
        model="qwen2.5-coder:7b",
        system="system",
        prompt="prompt",
        temperature=0.1,
        top_p=0.9,
    )
    assert result["response"].startswith("{")
    assert result["latency_ms"] >= 0
    request_json = respx.calls.last.request.content
    assert b'"format":"json"' in request_json
    assert b'"num_predict":64' in request_json


@respx.mock
async def test_ollama_generate_missing_model_has_actionable_error() -> None:
    provider = OllamaProvider("http://ollama.test")
    respx.post("http://ollama.test/api/generate").mock(
        return_value=Response(404, json={"error": "model 'qwen2.5-coder:7b' not found"})
    )

    with pytest.raises(HTTPStatusError) as exc:
        await provider.generate(
            model="qwen2.5-coder:7b",
            system="system",
            prompt="prompt",
            temperature=0.1,
            top_p=0.9,
        )

    message = str(exc.value)
    assert "Ollama model 'qwen2.5-coder:7b' is not available" in message
    assert "ollama pull qwen2.5-coder:7b" in message


@respx.mock
async def test_ollama_chat() -> None:
    provider = OllamaProvider("http://ollama.test")
    respx.post("http://ollama.test/api/chat").mock(
        return_value=Response(200, json={"message": {"role": "assistant", "content": '{"type":"final"}'}})
    )

    result = await provider.chat(
        model="qwen2.5:latest",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.1,
        top_p=0.9,
    )

    assert result["message"]["role"] == "assistant"
    assert result["latency_ms"] >= 0
    assert b'"format":"json"' in respx.calls.last.request.content
