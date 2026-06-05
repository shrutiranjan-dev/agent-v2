import httpx

from backend.app.core.config import get_settings


async def clickhouse_health() -> dict[str, str]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"http://{settings.clickhouse_host}:{settings.clickhouse_port}/ping")
        response.raise_for_status()
        return {"status": "ok"}

