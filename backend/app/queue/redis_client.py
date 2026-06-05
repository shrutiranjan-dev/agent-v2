import redis.asyncio as redis

from backend.app.core.config import get_settings


def get_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def redis_health() -> dict[str, str]:
    client = get_redis()
    try:
        pong = await client.ping()
        return {"status": "ok" if pong else "failed"}
    finally:
        await client.aclose()

