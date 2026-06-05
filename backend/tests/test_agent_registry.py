from backend.app.agents.registry import agent_registry


def test_native_agents_are_registered() -> None:
    agents = {agent.id: agent for agent in agent_registry.list(include_hidden=True)}
    assert {"build", "plan", "general", "explore", "summary", "compaction"}.issubset(agents)
    assert agents["summary"].hidden
    assert "write.file" in agents["build"].allowed_tools
    assert "write.file" not in agents["plan"].allowed_tools
    for agent in agents.values():
        assert agent.system_prompt
        assert agent.llm.provider == "ollama"
        assert agent.llm.model
        assert agent.max_steps > 0
        assert "*" not in agent.allowed_tools
