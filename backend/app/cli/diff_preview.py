from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

FILE_MUTATION_KEYS = {"write.file", "edit.file", "patch.apply"}


def extract_diff_preview(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    diff = metadata.get("diff_preview") or payload.get("diff_preview") or input_payload.get("diff_preview")
    paths = metadata.get("target_paths") or payload.get("target_paths") or _target_paths(input_payload)
    operation = metadata.get("operation_type") or payload.get("operation_type") or _operation_type(payload)
    return {
        "diff": diff if isinstance(diff, str) and diff.strip() else None,
        "target_paths": paths,
        "operation_type": operation,
        "risk_level": metadata.get("risk_level") or payload.get("risk_level") or "unknown",
    }


def diff_preview_panel(payload: dict[str, Any]) -> Panel:
    preview = extract_diff_preview(payload)
    paths = ", ".join(preview["target_paths"]) if preview["target_paths"] else "unknown target"
    title = f"{preview['operation_type']} -> {paths}"
    if preview["diff"]:
        return Panel(Syntax(preview["diff"], "diff", word_wrap=True), title=title, border_style="yellow")
    fallback = Text()
    fallback.append("Diff preview unavailable.\n", style="yellow")
    fallback.append(f"Targets: {paths}\n")
    fallback.append(f"Risk: {preview['risk_level']}")
    return Panel(fallback, title=title, border_style="yellow")


def should_show_diff(permission_or_event: dict[str, Any]) -> bool:
    key = str(
        permission_or_event.get("permission_key")
        or permission_or_event.get("tool_name")
        or permission_or_event.get("payload", {}).get("permission_key")
        or ""
    )
    return key in FILE_MUTATION_KEYS


def _target_paths(input_payload: dict[str, Any]) -> list[str]:
    path = input_payload.get("path") or input_payload.get("file_path")
    if isinstance(path, str):
        return [path]
    paths = input_payload.get("paths")
    if isinstance(paths, list):
        return [str(item) for item in paths]
    return []


def _operation_type(payload: dict[str, Any]) -> str:
    key = str(payload.get("permission_key") or payload.get("tool_name") or "file change")
    return {
        "write.file": "write",
        "edit.file": "edit",
        "patch.apply": "patch",
    }.get(key, key)
