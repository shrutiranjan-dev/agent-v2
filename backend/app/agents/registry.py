from backend.app.agents.base import AgentDefinition, ModelConfig
from backend.app.agents.build_agent import build_agent
from backend.app.agents.compaction_agent import compaction_agent
from backend.app.agents.explore_agent import explore_agent
from backend.app.agents.general_agent import general_agent
from backend.app.agents.plan_agent import plan_agent
from backend.app.agents.summary_agent import summary_agent
from backend.app.core.config import get_settings
from backend.app.core.errors import NotFoundError
from backend.app.providers.router import select_model_for_agent


class AgentRegistry:
    def __init__(self) -> None:
        settings = get_settings()
        fallback = ModelConfig(provider="ollama", model=settings.default_ollama_model)
        models = {
            agent_id: ModelConfig(
                provider=capability.provider,
                model=capability.name,
                supports_json_protocol=capability.supports_json_protocol,
                context_window=capability.context_window,
                max_output_tokens=capability.max_output_tokens,
            )
            for agent_id, capability in {
                agent_id: select_model_for_agent(agent_id, requires_json_protocol=True)
                for agent_id in ["build", "plan", "general", "explore", "summary", "compaction"]
            }.items()
        }
        code_tools = [
            "code.index",
            "code.symbols",
            "code.definition",
            "code.references",
            "code.diagnostics",
            "code.map",
        ]
        read_tools = ["read.file", "grep.search", "glob.search", "todo.write", "question.ask", *code_tools]
        edit_tools = [
            *read_tools,
            "write.file",
            "edit.file",
            "patch.apply",
            "bash.run",
        ]
        self._agents: dict[str, AgentDefinition] = {
            "build": build_agent(models.get("build", fallback), edit_tools),
            "plan": plan_agent(models.get("plan", fallback), read_tools),
            "general": general_agent(models.get("general", fallback), edit_tools),
            "explore": explore_agent(models.get("explore", fallback), read_tools),
            "summary": summary_agent(models.get("summary", fallback)),
            "compaction": compaction_agent(models.get("compaction", fallback)),
        }

    def list(self, *, include_hidden: bool = False) -> list[AgentDefinition]:
        agents = list(self._agents.values())
        if not include_hidden:
            agents = [agent for agent in agents if not agent.hidden]
        return sorted(agents, key=lambda agent: (agent.hidden, agent.id))

    def get(self, agent_id: str) -> AgentDefinition:
        agent = self._agents.get(agent_id)
        if not agent:
            raise NotFoundError(f"Agent not found: {agent_id}")
        return agent


agent_registry = AgentRegistry()
