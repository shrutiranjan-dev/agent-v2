from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from backend.app.tools.base import BaseTool, ToolContext, ToolResult


class TodoItem(BaseModel):
    id: str | None = None
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"
    priority: Literal["low", "medium", "high"] = "medium"
    created_at: str | None = None
    updated_at: str | None = None


class TodoWriteInput(BaseModel):
    mode: Literal["replace", "update"] = "replace"
    todos: list[TodoItem] = Field(default_factory=list)
    item: TodoItem | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "TodoWriteInput":
        if self.mode == "replace" and self.item is not None and not self.todos:
            self.todos = [self.item]
        if self.mode == "update" and self.item is None:
            raise ValueError("item is required when mode='update'.")
        return self


class TodoWriteTool(BaseTool):
    name = "todo.write"
    title = "Write Todos"
    description = "Replace or update the session-scoped todo list."
    category = "planning"
    input_model = TodoWriteInput
    permission_key = "todo.write"
    risk_level = "low"
    timeout_seconds = 5
    examples = [
        {"mode": "replace", "todos": [{"content": "Inspect files", "status": "in_progress", "priority": "high"}]},
        {"mode": "update", "item": {"id": "todo_1", "content": "Run tests", "status": "completed", "priority": "high"}},
    ]

    async def run(self, input_data: TodoWriteInput, ctx: ToolContext) -> ToolResult:
        now = datetime.now(UTC).isoformat()
        if input_data.mode == "replace":
            todos = [normalize_todo(item, now=now) for item in input_data.todos]
        else:
            assert input_data.item is not None
            todos = [normalize_todo(input_data.item, now=now)]
        active = len([item for item in todos if item["status"] not in {"completed", "cancelled"}])
        return ToolResult(
            title=f"{active} active todos",
            output={"mode": input_data.mode, "todos": todos, "active": active},
            metadata={"mode": input_data.mode, "todos": todos, "active": active},
        )


def normalize_todo(item: TodoItem, *, now: str) -> dict:
    data = item.model_dump(mode="json")
    data["id"] = data["id"] or f"todo_{uuid4().hex[:12]}"
    data["created_at"] = data["created_at"] or now
    data["updated_at"] = now
    return data
