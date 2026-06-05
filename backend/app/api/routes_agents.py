from fastapi import APIRouter

from backend.app.agents.registry import agent_registry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(include_hidden: bool = False) -> dict:
    return {
        "agents": [
            agent.model_dump(by_alias=True) for agent in agent_registry.list(include_hidden=include_hidden)
        ]
    }
