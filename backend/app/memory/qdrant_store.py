from __future__ import annotations

from typing import Any

import httpx

from backend.app.core.config import get_settings
from backend.app.core.redaction import redact_data


class QdrantMemoryStore:
    @property
    def enabled(self) -> bool:
        return get_settings().qdrant.enabled

    @property
    def collection(self) -> str:
        return get_settings().qdrant.collection

    async def health(self) -> dict[str, str]:
        if not self.enabled:
            return {"status": "degraded", "reason": "qdrant memory store disabled"}
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{get_settings().qdrant_url.rstrip('/')}/healthz")
            response.raise_for_status()
            return {"status": "ok"}

    async def upsert(
        self,
        *,
        point_id: str,
        vector: list[float] | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "degraded", "reason": "qdrant disabled"}
        if vector is None:
            return {"status": "degraded", "reason": "embedding unavailable"}
        body = {"points": [{"id": point_id, "vector": vector, "payload": redact_data(payload)}]}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{get_settings().qdrant_url.rstrip('/')}/collections/{self.collection}/points",
                json=body,
            )
            response.raise_for_status()
            return {"status": "ok", "response": redact_data(response.json())}


qdrant_memory_store = QdrantMemoryStore()


async def qdrant_health() -> dict[str, str]:
    return await qdrant_memory_store.health()
