from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes_agents import router as agents_router
from backend.app.api.routes_artifacts import router as artifacts_router
from backend.app.api.routes_codeintel import router as codeintel_router
from backend.app.api.routes_health import router as health_router
from backend.app.api.routes_human_input import router as human_input_router
from backend.app.api.routes_mcp import router as mcp_router
from backend.app.api.routes_memory import router as memory_router
from backend.app.api.routes_messages import router as messages_router
from backend.app.api.routes_models import router as models_router
from backend.app.api.routes_permissions import router as permissions_router
from backend.app.api.routes_plugins import router as plugins_router
from backend.app.api.routes_sessions import router as sessions_router
from backend.app.api.routes_system_events import router as system_events_router
from backend.app.api.routes_tools import router as tools_router
from backend.app.api.websocket import router as websocket_router
from backend.app.core.config import get_settings
from backend.app.core.errors import install_error_handlers
from backend.app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Local Agent Platform",
        version="0.1.0",
        description="Python local-first multi-agent runtime with Ollama-only model provider.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(agents_router)
    app.include_router(tools_router)
    app.include_router(sessions_router)
    app.include_router(messages_router)
    app.include_router(permissions_router)
    app.include_router(human_input_router)
    app.include_router(memory_router)
    app.include_router(codeintel_router)
    app.include_router(mcp_router)
    app.include_router(plugins_router)
    app.include_router(artifacts_router)
    app.include_router(system_events_router)
    app.include_router(websocket_router)
    return app


app = create_app()
