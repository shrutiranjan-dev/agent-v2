import subprocess

import typer
import uvicorn

from backend.app.core.config import get_settings

app = typer.Typer(help="Local Agent Platform CLI")


@app.command()
def serve() -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.env == "development",
    )


@app.command()
def migrate() -> None:
    subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)

