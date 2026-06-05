from __future__ import annotations

from backend.app.core.errors import NotFoundError
from backend.app.tools.base import BaseTool
from backend.app.tools.bash import BashRunTool
from backend.app.tools.codeintel import (
    CodeDefinitionTool,
    CodeDiagnosticsTool,
    CodeIndexTool,
    CodeMapTool,
    CodeReferencesTool,
    CodeSymbolsTool,
)
from backend.app.tools.edit import EditFileTool
from backend.app.tools.glob import GlobSearchTool
from backend.app.tools.grep import GrepSearchTool
from backend.app.tools.patch import PatchApplyTool
from backend.app.tools.question import QuestionAskTool
from backend.app.tools.read import ReadFileTool
from backend.app.tools.todo import TodoWriteTool
from backend.app.tools.write import WriteFileTool


class ToolRegistry:
    def __init__(self) -> None:
        tools: list[BaseTool] = [
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            GrepSearchTool(),
            GlobSearchTool(),
            BashRunTool(),
            PatchApplyTool(),
            TodoWriteTool(),
            QuestionAskTool(),
            CodeIndexTool(),
            CodeSymbolsTool(),
            CodeDefinitionTool(),
            CodeReferencesTool(),
            CodeDiagnosticsTool(),
            CodeMapTool(),
        ]
        self._tools = {tool.name: tool for tool in tools}
        self._native_names = set(self._tools)

    def list(self) -> list[dict]:
        return [tool.schema() for tool in sorted(self._tools.values(), key=lambda item: item.name)]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str, *, include_disabled: bool = False) -> BaseTool:
        tool = self._tools.get(name)
        if not tool:
            raise NotFoundError(f"Tool not found: {name}")
        if not tool.enabled and not include_disabled:
            raise NotFoundError(f"Tool is disabled: {name}")
        return tool

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        if name in self._native_names:
            return
        self._tools.pop(name, None)

    def clear_external(self, prefix: str | None = None) -> None:
        for name in list(self._tools):
            if name in self._native_names:
                continue
            if prefix is None or name.startswith(prefix):
                self._tools.pop(name, None)


tool_registry = ToolRegistry()
