import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from backend.app.analytics.clickhouse import clickhouse_health
from backend.app.artifacts.minio_store import minio_health
from backend.app.db.postgres import postgres_health
from backend.app.memory.graph_store import neo4j_health
from backend.app.memory.qdrant_store import qdrant_health
from backend.app.providers.ollama import ollama_provider
from backend.app.queue.redis_client import redis_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent-platform-python"}


async def _check(name: str, fn: Callable[[], Awaitable[dict]]) -> tuple[str, dict]:
    try:
        return name, await fn()
    except Exception as exc:
        return name, {"status": "error", "error": str(exc)}


@router.get("/health/dependencies")
async def dependency_health() -> dict:
    checks = await asyncio.gather(
        _check("postgres", postgres_health),
        _check("redis", redis_health),
        _check("qdrant", qdrant_health),
        _check("neo4j", neo4j_health),
        _check("minio", minio_health),
        _check("clickhouse", clickhouse_health),
        _check("ollama", ollama_provider.health),
    )
    data = dict(checks)
    overall = "ok" if all(item.get("status") == "ok" for item in data.values()) else "degraded"
    return {"status": overall, "dependencies": data}

