from neo4j import AsyncGraphDatabase

from backend.app.core.config import get_settings


async def neo4j_health() -> dict[str, str]:
    settings = get_settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        await driver.verify_connectivity()
        return {"status": "ok"}
    finally:
        await driver.close()

