import time
from typing import Any

import httpx

from backend.app.core.config import get_settings
from backend.app.core.redaction import redact_data, redact_text


class OllamaProvider:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or get_settings().ollama_base_url).rstrip("/")

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return {"status": "ok", "models": len(data.get("models", [])), "base_url": self.base_url}

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json().get("models", [])

    async def pull_model(self, model: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{self.base_url}/api/pull",
                json={"name": model, "stream": False},
            )
            response.raise_for_status()
            return response.json()

    async def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float,
        top_p: float,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        settings = get_settings()
        async with httpx.AsyncClient(timeout=settings.ollama.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": temperature,
                        "top_p": top_p,
                        "num_predict": settings.ollama_num_predict,
                    },
                },
            )
            self._raise_for_status(response, model=model)
            data = redact_data(response.json())
            data["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return data

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        top_p: float,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        settings = get_settings()
        async with httpx.AsyncClient(timeout=settings.ollama.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": temperature,
                        "top_p": top_p,
                        "num_predict": settings.ollama_num_predict,
                    },
                },
            )
            self._raise_for_status(response, model=model)
            data = redact_data(response.json())
            data["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return data

    async def embed(self, *, model: str, input_text: str) -> dict[str, Any]:
        started = time.perf_counter()
        settings = get_settings()
        async with httpx.AsyncClient(timeout=settings.ollama.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": input_text},
            )
            self._raise_for_status(response, model=model)
            data = redact_data(response.json())
            data["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return data

    def _raise_for_status(self, response: httpx.Response, *, model: str | None = None) -> None:
        if response.is_success:
            return

        detail = self._error_detail(response)
        if response.status_code == 404 and model:
            message = (
                f"Ollama model '{model}' is not available from {self.base_url}. "
                f"Pull it with `ollama pull {model}` or use a model returned by /models. "
                f"Ollama response: {detail}"
            )
        else:
            message = (
                f"Ollama request failed with HTTP {response.status_code} from {self.base_url}. "
                f"Ollama response: {detail}"
            )
        raise httpx.HTTPStatusError(message, request=response.request, response=response)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return redact_text(text or response.reason_phrase)
        if isinstance(payload, dict):
            error = payload.get("error") or payload.get("message") or payload
            return redact_text(str(error))
        return redact_text(str(payload))


ollama_provider = OllamaProvider()
