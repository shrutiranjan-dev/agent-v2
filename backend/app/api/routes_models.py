from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.providers.ollama import ollama_provider
from backend.app.providers.router import capability_for_model

router = APIRouter(prefix="/models", tags=["models"])


class PullModelRequest(BaseModel):
    model: str


@router.get("")
async def list_models() -> dict:
    models = await ollama_provider.list_models()
    return {
        "provider": "ollama",
        "models": [
            {
                **model,
                "capabilities": capability_for_model(str(model.get("name", ""))).model_dump(),
            }
            for model in models
        ],
    }


@router.post("/pull")
async def pull_model(payload: PullModelRequest) -> dict:
    return {"provider": "ollama", "result": await ollama_provider.pull_model(payload.model)}
