from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MessagePart(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["text", "tool-result", "summary", "error"]
    text: str | None = None
    tool: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def text_part(text: str) -> dict[str, Any]:
    return MessagePart(type="text", text=text).model_dump(exclude_none=True)


def tool_result_part(tool: str, text: str) -> dict[str, Any]:
    return MessagePart(type="tool-result", tool=tool, text=text).model_dump(exclude_none=True)


def validate_message_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [MessagePart.model_validate(part).model_dump(exclude_none=True) for part in parts]
