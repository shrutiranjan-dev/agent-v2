import asyncio
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str
    detail: Any | None = None
    recoverable: bool = True


class ToolResult(BaseModel):
    title: str = ""
    ok: bool = True
    output: Any = None
    error: ToolError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    redacted: bool = False
    truncated: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None

    @classmethod
    def failure(
        cls,
        *,
        code: str,
        message: str,
        detail: Any | None = None,
        recoverable: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            output=None,
            error=ToolError(code=code, message=message, detail=detail, recoverable=recoverable),
            metadata=metadata or {},
        )


class ToolContext(BaseModel):
    organization_id: UUID
    project_id: UUID
    workspace_id: UUID
    session_id: UUID
    agent_run_id: UUID | None = None
    tool_call_id: UUID | None = None
    agent_id: str
    workspace_root: Path
    db: Any | None = None

    model_config = {"arbitrary_types_allowed": True}


class BaseTool(ABC):
    name: str
    title: str = ""
    description: str
    category: str = "filesystem"
    input_model: type[BaseModel]
    output_model: type[ToolResult] = ToolResult
    permission_key: str
    risk_level: str = "low"
    requires_workspace: bool = True
    supports_artifacts: bool = False
    timeout_seconds: int = 30
    max_output_chars: int = 20000
    examples: list[dict[str, Any]] = []
    enabled: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "category": self.category,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
            "permission_key": self.permission_key,
            "risk_level": self.risk_level,
            "requires_workspace": self.requires_workspace,
            "supports_artifacts": self.supports_artifacts,
            "timeout_seconds": self.timeout_seconds,
            "max_output_chars": self.max_output_chars,
            "examples": self.examples,
            "enabled": self.enabled,
        }

    def resource(self, input_data: BaseModel, workspace_root: Path) -> str:
        return "*"

    async def run_with_timeout(self, input_data: BaseModel, ctx: ToolContext) -> ToolResult:
        started = datetime.now(UTC)
        try:
            result = await asyncio.wait_for(self.run(input_data, ctx), timeout=self.timeout_seconds)
        except TimeoutError:
            finished = datetime.now(UTC)
            return ToolResult.failure(
                code="tool_timeout",
                message=f"Tool {self.name} timed out after {self.timeout_seconds}s.",
                recoverable=True,
                metadata={"tool": self.name, "timeout_seconds": self.timeout_seconds},
            ).model_copy(
                update={
                    "started_at": started,
                    "finished_at": finished,
                    "duration_ms": duration_ms(started, finished),
                }
            )
        except PermissionError as exc:
            finished = datetime.now(UTC)
            return ToolResult.failure(
                code="permission_blocked",
                message=str(exc),
                recoverable=False,
                metadata={"tool": self.name},
            ).model_copy(
                update={
                    "started_at": started,
                    "finished_at": finished,
                    "duration_ms": duration_ms(started, finished),
                }
            )
        except Exception as exc:
            finished = datetime.now(UTC)
            return ToolResult.failure(
                code="tool_error",
                message=str(exc),
                recoverable=True,
                metadata={"tool": self.name, "error_type": type(exc).__name__},
            ).model_copy(
                update={
                    "started_at": started,
                    "finished_at": finished,
                    "duration_ms": duration_ms(started, finished),
                }
            )
        finished = datetime.now(UTC)
        result.started_at = result.started_at or started
        result.finished_at = result.finished_at or finished
        result.duration_ms = result.duration_ms if result.duration_ms is not None else duration_ms(started, finished)
        if isinstance(result.output, str) and len(result.output) > self.max_output_chars:
            result.output = result.output[: self.max_output_chars] + "\n...output truncated..."
            result.truncated = True
        if result.metadata.get("truncated") is True:
            result.truncated = True
        return result

    @abstractmethod
    async def run(self, input_data: BaseModel, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError


def resolve_workspace_path(workspace_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve()


def is_inside(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def ensure_inside_workspace(workspace_root: Path, path: Path, *, action: str = "access") -> None:
    if not is_inside(workspace_root, path):
        raise PermissionError(f"Cannot {action} outside workspace root: {path}")


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256(content: bytes | str) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return sha256(data).hexdigest()


def looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:4096]
    non_printable = sum(1 for byte in sample if byte < 9 or (13 < byte < 32))
    return non_printable / max(len(sample), 1) > 0.30


def duration_ms(started: datetime, finished: datetime) -> int:
    return max(int((finished - started).total_seconds() * 1000), 0)
