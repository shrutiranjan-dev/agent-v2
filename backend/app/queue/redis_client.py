from pathlib import Path
from urllib.parse import urlsplit

import redis.asyncio as redis

from backend.app.core.config import get_settings


def get_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


def redis_transport_available() -> bool:
    host = urlsplit(get_settings().redis_url).hostname
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if Path("/.dockerenv").exists():
        return True
    return host != "redis"


async def redis_health() -> dict[str, str]:
    if not redis_transport_available():
        return {"status": "failed"}
    client = get_redis()
    try:
        pong = await client.ping()
        return {"status": "ok" if pong else "failed"}
    finally:
        await client.aclose()

