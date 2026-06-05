from pathlib import Path

from backend.app.permissions.models import PermissionAction
from backend.app.permissions.policy import evaluate_default_policy, shell_is_destructive


def test_default_read_is_allowed() -> None:
    decision = evaluate_default_policy(
        permission_key="read.file",
        resource="/workspace/README.md",
        input_json={"path": "/workspace/README.md"},
        workspace_root=Path("/workspace"),
    )
    assert decision.action == PermissionAction.ALLOW


def test_default_write_asks() -> None:
    decision = evaluate_default_policy(
        permission_key="write.file",
        resource="/workspace/new.txt",
        input_json={"path": "/workspace/new.txt"},
        workspace_root=Path("/workspace"),
    )
    assert decision.action == PermissionAction.ASK


def test_external_directory_access_asks_even_for_read() -> None:
    decision = evaluate_default_policy(
        permission_key="read.file",
        resource="/etc/passwd",
        input_json={"path": "/etc/passwd"},
        workspace_root=Path("/workspace"),
    )
    assert decision.action == PermissionAction.ASK
    assert decision.permission_key == "external_directory"


def test_external_directory_write_is_denied_by_default() -> None:
    decision = evaluate_default_policy(
        permission_key="write.file",
        resource="/tmp/outside.txt",
        input_json={"path": "../outside.txt"},
        workspace_root=Path("/workspace"),
    )
    assert decision.action == PermissionAction.DENY
    assert decision.permission_key == "external_directory"


def test_secret_env_read_asks_but_example_allows() -> None:
    env_decision = evaluate_default_policy(
        permission_key="read.file",
        resource="/workspace/.env",
        input_json={"path": ".env"},
        workspace_root=Path("/workspace"),
    )
    assert env_decision.action == PermissionAction.ASK
    assert env_decision.permission_key == "secret_file"

    example_decision = evaluate_default_policy(
        permission_key="read.file",
        resource="/workspace/.env.example",
        input_json={"path": ".env.example"},
        workspace_root=Path("/workspace"),
    )
    assert example_decision.action == PermissionAction.ALLOW


def test_private_key_read_is_denied_case_insensitively() -> None:
    decision = evaluate_default_policy(
        permission_key="read.file",
        resource="/workspace/ID_RSA",
        input_json={"path": "ID_RSA"},
        workspace_root=Path("/workspace"),
    )
    assert decision.action == PermissionAction.DENY
    assert decision.permission_key == "secret_file"


def test_path_traversal_and_symlink_resolved_path_trigger_external_directory(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = workspace / "link.txt"
    link.symlink_to(target)

    decision = evaluate_default_policy(
        permission_key="read.file",
        resource=str(link.resolve()),
        input_json={"path": "link.txt"},
        workspace_root=workspace,
    )

    assert decision.action == PermissionAction.ASK
    assert decision.permission_key == "external_directory"


def test_destructive_shell_is_denied() -> None:
    assert shell_is_destructive("rm -rf /tmp/demo")
    decision = evaluate_default_policy(
        permission_key="bash.run",
        resource="rm -rf /tmp/demo",
        input_json={"command": "rm -rf /tmp/demo"},
        workspace_root=Path("/workspace"),
    )
    assert decision.action == PermissionAction.DENY
