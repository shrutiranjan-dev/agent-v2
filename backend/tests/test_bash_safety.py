from pathlib import Path
from uuid import uuid4

from backend.app.core.redaction import REDACTED
from backend.app.permissions.models import PermissionAction
from backend.app.permissions.policy import evaluate_default_policy, shell_is_destructive
from backend.app.tools.base import ToolContext
from backend.app.tools.bash import BashRunInput, BashRunTool


def _ctx(workspace_root: Path) -> ToolContext:
    return ToolContext(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_id="test",
        workspace_root=workspace_root,
    )


def test_destructive_shell_patterns_are_denied() -> None:
    commands = [
        "rm -rf /",
        "rm -rf *",
        "sudo rm -rf /tmp/demo",
        "mkfs.ext4 /dev/sdz",
        "dd if=/dev/zero of=/dev/sdz",
        "shutdown now",
        "reboot",
        "poweroff",
        "chmod -R 777 /",
        "chown -R root /tmp/demo",
        ":(){ :|:& };:",
    ]

    for command in commands:
        assert shell_is_destructive(command), command
        decision = evaluate_default_policy(
            permission_key="bash.run",
            resource="/workspace",
            input_json={"command": command},
            workspace_root=Path("/workspace"),
        )
        assert decision.action == PermissionAction.DENY


def test_bash_cwd_outside_workspace_is_denied(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    decision = evaluate_default_policy(
        permission_key="bash.run",
        resource=str(outside),
        input_json={"command": "pwd", "workdir": str(outside)},
        workspace_root=workspace,
    )

    assert decision.action == PermissionAction.DENY
    assert decision.permission_key == "external_directory"


async def test_bash_tool_blocks_cwd_outside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    tool = BashRunTool()
    try:
        await tool.run(BashRunInput(command="pwd", workdir=str(outside)), _ctx(workspace))
    except PermissionError as exc:
        assert "outside workspace" in str(exc)
    else:
        raise AssertionError("expected bash cwd outside workspace to be blocked")


async def test_bash_env_secrets_are_not_exposed(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("API_TOKEN", "super-secret-token")

    result = await BashRunTool().run(
        BashRunInput(command="python3 -c 'import os; print(os.getenv(\"API_TOKEN\", \"missing\"))'", timeout=5),
        _ctx(workspace),
    )

    assert "super-secret-token" not in result.output
    assert result.output.strip() == "missing"


async def test_bash_output_is_redacted_and_truncated(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await BashRunTool().run(
        BashRunInput(
            command="python3 -c 'print(\"API_TOKEN=super-secret\"); print(\"x\" * 25050)'",
            timeout=5,
        ),
        _ctx(workspace),
    )

    assert "super-secret" not in result.output
    assert REDACTED in result.output or result.metadata["truncated"]
    assert result.metadata["truncated"] is True
    assert result.output.startswith("...output truncated...")
