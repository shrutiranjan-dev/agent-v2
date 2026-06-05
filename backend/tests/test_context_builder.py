from backend.app.agents.registry import agent_registry
from backend.app.runtime.context_builder import ContextMessage, context_builder


def test_context_includes_system_prompt_protocol_and_latest_messages() -> None:
    agent = agent_registry.get("general")
    bundle = context_builder.build_from_messages(
        agent=agent,
        messages=[
            ContextMessage(role="user", content="hello"),
            ContextMessage(role="assistant", content="hi"),
        ],
        tools=[],
        char_budget=100_000,
    )

    assert agent.system_prompt in bundle.system_prompt
    assert '{"type":"final","content":"..."}' in bundle.system_prompt
    assert "USER:\nhello" in bundle.prompt
    assert "ASSISTANT:\nhi" in bundle.prompt


def test_context_excludes_old_messages_when_budget_is_exceeded() -> None:
    agent = agent_registry.get("general")
    empty_bundle = context_builder.build_from_messages(
        agent=agent,
        messages=[],
        tools=[],
        char_budget=100_000,
    )
    constrained_budget = len(empty_bundle.system_prompt) + 80

    bundle = context_builder.build_from_messages(
        agent=agent,
        messages=[
            ContextMessage(role="user", content="old " * 200),
            ContextMessage(role="user", content="new"),
        ],
        tools=[],
        char_budget=constrained_budget,
    )

    assert bundle.needs_compaction
    assert bundle.excluded_message_count == 1
    assert "USER:\nnew" in bundle.prompt
    assert "old old old" not in bundle.prompt
