import re
import shlex
from pathlib import Path

from backend.app.permissions.matcher import matches
from backend.app.permissions.models import PermissionAction, PermissionDecision
from backend.app.tools.base import is_inside

DEFAULT_TOOL_POLICY: dict[str, PermissionAction] = {
    "read.file": PermissionAction.ALLOW,
    "grep.search": PermissionAction.ALLOW,
    "glob.search": PermissionAction.ALLOW,
    "todo.write": PermissionAction.ALLOW,
    "question.ask": PermissionAction.ALLOW,
    "code.index": PermissionAction.ALLOW,
    "code.symbols": PermissionAction.ALLOW,
    "code.definition": PermissionAction.ALLOW,
    "code.references": PermissionAction.ALLOW,
    "code.diagnostics": PermissionAction.ALLOW,
    "code.map": PermissionAction.ALLOW,
    "write.file": PermissionAction.ASK,
    "edit.file": PermissionAction.ASK,
    "patch.apply": PermissionAction.ASK,
    "bash.run": PermissionAction.ASK,
}

DESTRUCTIVE_SHELL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"(^|[;&|]\s*)rm\s+(-[^\s]*[rf][^\s]*|-rf|-fr)\b",
        r"(^|[;&|]\s*)rm\s+(-[^\s]*[rf][^\s]*|-rf|-fr)\s+(/|\*)\s*($|[;&|])",
        r"(^|[;&|]\s*)sudo\s+",
        r"(^|[;&|]\s*)sudo\s+rm\b",
        r"(^|[;&|]\s*)mkfs(\.|\s|$)",
        r"(^|[;&|]\s*)dd\s+.*\bif=",
        r"(^|[;&|]\s*)dd\s+.*\bof=",
        r"(^|[;&|]\s*)shutdown\b",
        r"(^|[;&|]\s*)reboot\b",
        r"(^|[;&|]\s*)poweroff\b",
        r"(^|[;&|]\s*)chmod\s+-R\s+777\b",
        r"(^|[;&|]\s*)chmod\s+-R\s+777\s+/",
        r"(^|[;&|]\s*)chown\s+-R\b",
        r":\(\)\s*\{\s*:\|:",
    ]
]

SECRET_ASK_PATTERNS = [
    ".env",
    ".env.*",
    "credentials.json",
    "secrets.*",
    "*secret*",
    "*token*",
    "*credential*",
]

SECRET_DENY_PATTERNS = [
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
]

SECRET_ALLOW_EXACT = {
    ".env.example",
}

WRITE_PERMISSION_KEYS = {"write.file", "edit.file", "patch.apply"}
READ_PERMISSION_KEYS = {"read.file", "grep.search", "glob.search"}


def shell_is_destructive(command: str) -> bool:
    return any(pattern.search(command) for pattern in DESTRUCTIVE_SHELL_PATTERNS)


def shell_prefix(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command.strip().split(" ", 1)[0]
    if not tokens:
        return ""
    if len(tokens) >= 2 and tokens[0] in {"git", "docker", "docker-compose", "npm", "pnpm", "yarn"}:
        return " ".join(tokens[:2])
    return tokens[0]


def split_resource_paths(resource: str) -> list[str]:
    if resource in {"", "*"}:
        return []
    if "\n" in resource:
        return [part.strip() for part in resource.splitlines() if part.strip()]
    return [part.strip() for part in resource.split(",") if part.strip()]


def normalize_policy_path(raw: str, workspace_root: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve(strict=False)


def is_external_path(path: Path, workspace_root: Path) -> bool:
    return path.is_absolute() and not is_inside(workspace_root, path)


def secret_path_action(path: Path) -> PermissionAction | None:
    name = path.name
    lower_name = name.lower()
    if lower_name in SECRET_ALLOW_EXACT:
        return None
    for pattern in SECRET_DENY_PATTERNS:
        if matches(pattern, lower_name, case_sensitive=False):
            return PermissionAction.DENY
    for pattern in SECRET_ASK_PATTERNS:
        if matches(pattern, lower_name, case_sensitive=False):
            return PermissionAction.ASK
    return None


def evaluate_default_policy(
    *,
    permission_key: str,
    resource: str,
    input_json: dict,
    workspace_root: Path,
    external_write_policy: PermissionAction = PermissionAction.DENY,
) -> PermissionDecision:
    if permission_key == "bash.run":
        command = str(input_json.get("command", ""))
        if shell_is_destructive(command):
            return PermissionDecision(
                action=PermissionAction.DENY,
                reason="destructive shell command denied by default policy",
                permission_key=permission_key,
                resource=shell_prefix(command) or resource,
            )
        for raw in split_resource_paths(resource):
            path = normalize_policy_path(raw, workspace_root)
            if is_external_path(path, workspace_root):
                return PermissionDecision(
                    action=PermissionAction.DENY,
                    reason="external bash working directory denied by default policy",
                    permission_key="external_directory",
                    resource=str(path),
                )

    for raw in split_resource_paths(resource):
        path = normalize_policy_path(raw, workspace_root)
        if is_external_path(path, workspace_root):
            if permission_key in WRITE_PERMISSION_KEYS:
                return PermissionDecision(
                    action=external_write_policy,
                    reason="external directory write denied by default policy",
                    permission_key="external_directory",
                    resource=str(path),
                )
            if permission_key in READ_PERMISSION_KEYS:
                return PermissionDecision(
                    action=PermissionAction.ASK,
                    reason="external directory access requires approval",
                    permission_key="external_directory",
                    resource=str(path),
                )
        secret_action = secret_path_action(path)
        if secret_action == PermissionAction.DENY:
            return PermissionDecision(
                action=PermissionAction.DENY,
                reason="private key or binary secret file denied by default policy",
                permission_key="secret_file",
                resource=str(path),
            )
        if secret_action == PermissionAction.ASK:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason="secret-like file access requires approval",
                permission_key="secret_file",
                resource=str(path),
            )

    action = DEFAULT_TOOL_POLICY.get(permission_key, PermissionAction.ASK)
    return PermissionDecision(
        action=action,
        reason=f"default policy for {permission_key}",
        permission_key=permission_key,
        resource=resource or "*",
    )
