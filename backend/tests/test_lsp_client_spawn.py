from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.app.codeintel.lsp_client import LspClient, parse_lsp_command


def _lsp_settings(workspace_root: Path, command: str) -> SimpleNamespace:
    return SimpleNamespace(
        lsp=SimpleNamespace(
            python_command=command,
            workspace_root=workspace_root,
            startup_timeout_seconds=1,
            request_timeout_seconds=1,
            shutdown_timeout_seconds=1,
            max_response_chars=200_000,
        )
    )


def test_parse_lsp_command_single_binary() -> None:
    assert parse_lsp_command("pylsp") == ["pylsp"]


def test_parse_lsp_command_python_module() -> None:
    assert parse_lsp_command("python -m pylsp") == ["python", "-m", "pylsp"]


def test_parse_lsp_command_bash_script() -> None:
    assert parse_lsp_command("bash /tmp/run-pylsp.sh") == ["bash", "/tmp/run-pylsp.sh"]


def test_parse_lsp_command_preserves_quoted_windows_path() -> None:
    assert parse_lsp_command('"C:\\Path With Spaces\\python.exe" -m pylsp') == [
        "C:\\Path With Spaces\\python.exe",
        "-m",
        "pylsp",
    ]


def test_resolve_command_reports_script_diagnostics(monkeypatch, tmp_path) -> None:
    script_path = tmp_path / "run-pylsp.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda command: "/usr/bin/bash" if command == "bash" else None)

    info = LspClient()._resolve_command(f'bash "{script_path}"')

    assert info["spawn_argv"][0] == "/usr/bin/bash"
    assert info["executable"] == "bash"
    assert info["resolved_executable"] == "/usr/bin/bash"
    assert str(script_path) not in info["resolved_executable"]
    assert info["script_path"] == str(script_path)
    assert info["script_exists"] is True


def test_resolve_command_reports_missing_executable(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _command: None)

    info = LspClient()._resolve_command("missing-lsp-binary --flag")

    assert info["command_exists"] is False
    assert info["resolved_executable"] is None
    assert info["spawn_argv"] == ["missing-lsp-binary", "--flag"]


async def test_health_diagnostic_includes_spawn_argv_for_missing_executable(monkeypatch, tmp_path) -> None:
    settings = _lsp_settings(tmp_path, "missing-lsp-binary --flag")
    monkeypatch.setattr("backend.app.codeintel.lsp_client.get_settings", lambda: settings)
    monkeypatch.setattr("shutil.which", lambda _command: None)

    health = await LspClient().health(tmp_path)

    assert health["status"] == "failed"
    assert health["debug"]["spawn_argv"] == ["missing-lsp-binary", "--flag"]
    assert health["debug"]["command_exists"] is False
    assert health["debug"]["last_error_type"] == "RuntimeError"


def test_build_env_preserves_path(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    env = LspClient()._build_env()

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"
    assert env["LANG"] == "en_US.UTF-8"
    assert env["PYTHONUNBUFFERED"] == "1"
