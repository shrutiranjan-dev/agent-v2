import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from backend.app.core.redaction import redact_text, scrub_process_env
from backend.app.permissions.policy import shell_is_destructive
from backend.app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    is_inside,
    resolve_workspace_path,
)


class BashRunInput(BaseModel):
    command: str
    description: str = ""
    workdir: str | None = None
    timeout: int = Field(default=120, ge=1, le=1800)
    max_output_chars: int = Field(default=20000, ge=1000, le=100000)


class BashRunTool(BaseTool):
    name = "bash.run"
    title = "Run Bash"
    description = "Run a shell command in the workspace after permission approval."
    category = "shell"
    input_model = BashRunInput
    permission_key = "bash.run"
    risk_level = "high"
    timeout_seconds = 1800
    examples = [
        {"command": "pwd && ls", "description": "List workspace"},
        {"command": "pytest backend/tests", "timeout": 120},
    ]

    def resource(self, input_data: BashRunInput, workspace_root: Path) -> str:
        return str(resolve_workspace_path(workspace_root, input_data.workdir or "."))

    async def run(self, input_data: BashRunInput, ctx: ToolContext) -> ToolResult:
        cwd = resolve_workspace_path(ctx.workspace_root, input_data.workdir or ".")
        if not is_inside(ctx.workspace_root, cwd):
            raise PermissionError(f"bash cwd is outside workspace root: {cwd}")
        classification = classify_command(input_data.command)
        if classification["denied"]:
            return ToolResult.failure(
                code="destructive_command_denied",
                message=str(classification["reason"]),
                recoverable=False,
                metadata={"classification": classification, "cwd": str(cwd)},
            )
        command = normalize_command(input_data.command)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            env=scrub_process_env(os.environ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=input_data.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"bash command timed out after {input_data.timeout}s") from None
        text = stdout.decode("utf-8", errors="replace")
        truncated = len(text) > input_data.max_output_chars
        output = text[-input_data.max_output_chars :] if truncated else text
        if not output:
            output = "(no output)"
        if truncated:
            output = "...output truncated...\n" + output
        output = redact_text(output)
        return ToolResult(
            title=input_data.description or input_data.command,
            ok=proc.returncode == 0,
            output=output,
            metadata={
                "exit_code": proc.returncode,
                "status": "completed" if proc.returncode == 0 else "failed",
                "cwd": str(cwd),
                "truncated": truncated,
                "classification": classification,
            },
            truncated=truncated,
            redacted=output != text[-input_data.max_output_chars :] if truncated else output != text,
        )


def classify_command(command: str) -> dict[str, object]:
    risky_composition = any(token in command for token in ["&&", "||", ";", "|", "$(", "`"])
    if shell_is_destructive(command):
        return {
            "denied": True,
            "risk_level": "destructive",
            "reason": "Command matches destructive shell policy.",
            "risky_composition": risky_composition,
        }
    return {
        "denied": False,
        "risk_level": "medium" if risky_composition else "low",
        "reason": None,
        "risky_composition": risky_composition,
    }


def normalize_command(command: str) -> str:
    if os.name != "nt":
        return command
    python_executable = _resolve_python_executable()
    if not python_executable:
        return command
    match = re.match(r"^\s*python3\s+-c\s+'(?P<code>.*)'\s*$", command, flags=re.DOTALL)
    if match:
        return subprocess.list2cmdline([python_executable, "-c", match.group("code")])
    return command


def _resolve_python_executable() -> str | None:
    candidates = [sys.executable, shutil.which("python3"), shutil.which("python")]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.name.lower() in {"python.exe", "python3.exe"} and "windowsapps" in {part.lower() for part in path.parts}:
            continue
        if path.exists():
            return str(path)
    return None
