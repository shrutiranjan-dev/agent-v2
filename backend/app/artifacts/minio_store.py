from __future__ import annotations

import httpx

from backend.app.core.config import get_settings


async def minio_health() -> dict[str, str]:
    settings = get_settings()
    scheme = "https" if settings.minio_secure else "http"
    endpoint = settings.minio_endpoint.rstrip("/")
    url = f"{scheme}://{endpoint}/minio/health/live"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"status": "degraded", "reason": f"minio unavailable: {exc}"}
    return {"status": "ok"}
