from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.app.tools.base import BaseTool, ToolContext, ToolResult


class QuestionPrompt(BaseModel):
    id: str | None = None
    header: str | None = Field(default=None, max_length=32)
    question: str
    options: list[str] = Field(default_factory=list)


class QuestionAskInput(BaseModel):
    question: str | None = None
    details: dict[str, Any] | str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    choices: list[str] = Field(default_factory=list)
    allow_free_text: bool = True
    questions: list[QuestionPrompt] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_legacy_shape(self) -> "QuestionAskInput":
        if self.question:
            return self
        if self.questions:
            first = self.questions[0]
            self.question = first.question
            if not self.choices:
                self.choices = first.options
            if self.details is None:
                self.details = {
                    "legacy_questions": [question.model_dump(mode="json") for question in self.questions],
                    "header": first.header,
                    "id": first.id,
                }
            return self
        raise ValueError("question is required.")


class QuestionAskTool(BaseTool):
    name = "question.ask"
    title = "Ask Human"
    description = "Pause the agent run and ask the user for human input."
    category = "human_input"
    input_model = QuestionAskInput
    permission_key = "question.ask"
    risk_level = "low"
    requires_workspace = False
    timeout_seconds = 5
    examples = [
        {
            "question": "Which module should I update first?",
            "choices": ["backend", "frontend"],
            "allow_free_text": False,
            "timeout_seconds": 600,
        },
    ]

    async def run(self, input_data: QuestionAskInput, ctx: ToolContext) -> ToolResult:
        return ToolResult(
            title="Human input requested",
            output={
                "question": input_data.question,
                "details": input_data.details,
                "choices": input_data.choices,
                "allow_free_text": input_data.allow_free_text,
                "status": "requested",
            },
            metadata={
                "question": input_data.question,
                "details": input_data.details,
                "choices": input_data.choices,
                "allow_free_text": input_data.allow_free_text,
                "timeout_seconds": input_data.timeout_seconds,
            },
        )
