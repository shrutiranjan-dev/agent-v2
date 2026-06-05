import pytest

from backend.app.core.errors import NotFoundError
from backend.app.tools.registry import tool_registry


def test_native_tools_are_registered() -> None:
    names = tool_registry.names()
    assert "read.file" in names
    assert "write.file" in names
    assert "bash.run" in names
    assert "question.ask" in names


def test_tool_schema_contains_permission_key() -> None:
    read_tool = tool_registry.get("read.file").schema()
    assert read_tool["permission_key"] == "read.file"
    assert "input_schema" in read_tool


def test_native_tool_metadata_contract_is_complete() -> None:
    categories = {"filesystem", "search", "shell", "planning", "human_input", "mcp", "plugin"}
    risk_levels = {"low", "medium", "high", "destructive"}

    for schema in tool_registry.list():
        assert schema["name"]
        assert schema["title"]
        assert schema["description"]
        assert schema["category"] in categories
        assert schema["permission_key"]
        assert schema["risk_level"] in risk_levels
        assert isinstance(schema["requires_workspace"], bool)
        assert isinstance(schema["supports_artifacts"], bool)
        assert schema["timeout_seconds"] > 0
        assert schema["max_output_chars"] > 0
        assert isinstance(schema["examples"], list)
        assert isinstance(schema["enabled"], bool)
        assert "input_schema" in schema
        assert "output_schema" in schema


def test_disabled_tools_are_not_executable() -> None:
    tool = tool_registry.get("read.file")
    original = tool.enabled
    try:
        tool.enabled = False
        with pytest.raises(NotFoundError):
            tool_registry.get("read.file")
        assert tool_registry.get("read.file", include_disabled=True) is tool
    finally:
        tool.enabled = original
