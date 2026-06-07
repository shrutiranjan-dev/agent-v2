from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.codeintel.language import detect_language, lsp_language_id
from backend.app.codeintel.lsp_registry import (
    PRESETS,
    LspServerPreset,
    all_server_ids,
    get_preset,
    get_preset_for_file,
    get_preset_for_language,
    is_supported_code_file,
)
from backend.app.codeintel.lsp_service import lsp_service
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_codeintel import codeintel_test_settings, patch_codeintel_settings

FAKE_GENERIC_LSP_SERVER = Path(__file__).parent / "fixtures" / "fake_generic_lsp_server.py"


def _generic_settings(
    workspace_root: Path,
    *,
    go_enabled: bool = False,
    rust_enabled: bool = False,
    java_enabled: bool = False,
    ruby_enabled: bool = False,
    php_enabled: bool = False,
    csharp_enabled: bool = False,
    kotlin_enabled: bool = False,
    lua_enabled: bool = False,
    clangd_enabled: bool = False,
    fake_command: list[str] | str | None = None,
    startup_timeout: int = 5,
    request_timeout: int = 5,
) -> SimpleNamespace:
    base = codeintel_test_settings(
        workspace_root,
        lsp_enabled=False,
        ts_enabled=False,
        startup_timeout=startup_timeout,
        request_timeout=request_timeout,
    )
    if fake_command is None:
        cmd = [sys.executable, str(FAKE_GENERIC_LSP_SERVER), "--language=generic"]
    elif isinstance(fake_command, str):
        cmd = fake_command
    else:
        cmd = fake_command
    lsp = base.lsp
    lsp.go_enabled = go_enabled
    lsp.go_command = cmd
    lsp.go_workspace_root = None
    lsp.rust_enabled = rust_enabled
    lsp.rust_command = cmd
    lsp.rust_workspace_root = None
    lsp.java_enabled = java_enabled
    lsp.java_command = cmd
    lsp.java_workspace_root = None
    lsp.ruby_enabled = ruby_enabled
    lsp.ruby_command = cmd
    lsp.ruby_workspace_root = None
    lsp.php_enabled = php_enabled
    lsp.php_command = cmd
    lsp.php_workspace_root = None
    lsp.csharp_enabled = csharp_enabled
    lsp.csharp_command = cmd
    lsp.csharp_workspace_root = None
    lsp.kotlin_enabled = kotlin_enabled
    lsp.kotlin_command = cmd
    lsp.kotlin_workspace_root = None
    lsp.lua_enabled = lua_enabled
    lsp.lua_command = cmd
    lsp.lua_workspace_root = None
    lsp.clangd_enabled = clangd_enabled
    lsp.clangd_command = cmd
    lsp.clangd_workspace_root = None
    return base


def test_registry_contains_expected_presets() -> None:
    server_ids = set(all_server_ids())
    assert {"python", "typescript", "typescriptreact", "javascript", "javascriptreact",
            "go", "rust", "java", "ruby", "php", "csharp", "kotlin", "lua", "clangd"} <= server_ids


def test_registry_extension_to_language_mapping() -> None:
    assert detect_language("a.go") == "go"
    assert detect_language("a.rs") == "rust"
    assert detect_language("a.java") == "java"
    assert detect_language("a.cpp") == "cpp"
    assert detect_language("a.hpp") == "cpp"
    assert detect_language("a.c") == "c"
    assert detect_language("a.h") == "c"
    assert detect_language("a.rb") == "ruby"
    assert detect_language("a.php") == "php"
    assert detect_language("a.cs") == "csharp"
    assert detect_language("a.kt") == "kotlin"
    assert detect_language("a.kts") == "kotlin"
    assert detect_language("a.lua") == "lua"
    assert detect_language("a.py") == "python"
    assert detect_language("a.ts") == "typescript"
    assert detect_language("a.tsx") == "typescriptreact"
    assert detect_language("a.js") == "javascript"
    assert detect_language("a.jsx") == "javascriptreact"
    assert detect_language("a.bin") is None


def test_registry_lsp_language_id_matches_extension() -> None:
    assert lsp_language_id("go") == "go"
    assert lsp_language_id("rust") == "rust"
    assert lsp_language_id("java") == "java"
    assert lsp_language_id("c") == "c"
    assert lsp_language_id("cpp") == "cpp"
    assert lsp_language_id("ruby") == "ruby"
    assert lsp_language_id("php") == "php"
    assert lsp_language_id("csharp") == "csharp"
    assert lsp_language_id("kotlin") == "kotlin"
    assert lsp_language_id("lua") == "lua"


def test_registry_supported_code_files() -> None:
    assert is_supported_code_file("a.go")
    assert is_supported_code_file("a.rs")
    assert is_supported_code_file("a.java")
    assert is_supported_code_file("a.cpp")
    assert is_supported_code_file("a.h")
    assert is_supported_code_file("a.rb")
    assert is_supported_code_file("a.php")
    assert is_supported_code_file("a.cs")
    assert is_supported_code_file("a.kt")
    assert is_supported_code_file("a.lua")
    assert is_supported_code_file("a.py")
    assert is_supported_code_file("a.ts")
    assert is_supported_code_file("a.tsx")
    assert is_supported_code_file("a.js")
    assert is_supported_code_file("a.jsx")
    assert not is_supported_code_file("a.md")
    assert not is_supported_code_file("a.txt")
    assert not is_supported_code_file("a.bin")


def test_registry_presets_have_install_hints() -> None:
    for preset in PRESETS:
        assert isinstance(preset, LspServerPreset)
        assert preset.server_id
        assert preset.default_command
        assert preset.install_hint_windows
        assert preset.install_hint_linux_ci


def test_registry_preset_helpers_consistent() -> None:
    for preset in PRESETS:
        assert get_preset(preset.server_id) is preset
        for ext in preset.file_extensions:
            assert get_preset_for_file(f"foo{ext}") is preset
        for lang in preset.languages:
            assert get_preset_for_language(lang) is preset


async def test_health_includes_all_registry_presets(monkeypatch, tmp_path) -> None:
    settings = _generic_settings(tmp_path)
    patch_codeintel_settings(monkeypatch, settings)
    health = await lsp_service.health()
    await lsp_service.shutdown()
    assert "lsp_servers" in health
    servers = health["lsp_servers"]
    for sid in ("python", "typescript", "go", "rust", "java", "clangd", "ruby", "php", "csharp", "kotlin", "lua"):
        assert sid in servers, f"Missing server in health: {sid}"
        payload = servers[sid]
        assert payload["server_id"] == sid
        assert payload["enabled"] is False
        assert payload["real_lsp_enabled"] is False


async def test_disabled_new_language_returns_static_fallback(monkeypatch, tmp_path) -> None:
    settings = _generic_settings(tmp_path, go_enabled=False)
    patch_codeintel_settings(monkeypatch, settings)
    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    result = await lsp_service.document_symbols(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file_path="main.go",
        limit=20,
    )
    await lsp_service.shutdown()

    assert result.source == "static_fallback"
    assert result.language == "go"
    assert result.lsp_language == "go"
    assert result.lsp_server == "none"
    assert result.fallback_reason == "go_lsp_disabled"


async def test_missing_command_falls_back_to_static(monkeypatch, tmp_path) -> None:
    settings = _generic_settings(
        tmp_path,
        go_enabled=True,
        fake_command="definitely-missing-go-server",
    )
    patch_codeintel_settings(monkeypatch, settings)
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")

    result = await lsp_service.document_symbols(
        FakeAsyncSession(),
        workspace_id=uuid4(),
        file_path="main.go",
        limit=20,
    )
    await lsp_service.shutdown()

    assert result.source == "static_fallback"
    assert result.language == "go"
    assert result.lsp_server == "none"
    assert result.lsp_status in {"failed", "missing_command"}


async def _run_fake_lsp(
    monkeypatch, tmp_path, server_id: str, file_path: str, source_text: str, language: str | None = None
):
    cmd = [sys.executable, str(FAKE_GENERIC_LSP_SERVER), f"--language={server_id}"]
    settings = _generic_settings(tmp_path, **{f"{server_id}_enabled": True}, fake_command=cmd)
    patch_codeintel_settings(monkeypatch, settings)

    (tmp_path / Path(file_path).name).write_text(source_text, encoding="utf-8")

    try:
        result = await lsp_service.document_symbols(
            FakeAsyncSession(),
            workspace_id=uuid4(),
            file_path=file_path,
            limit=20,
            language=language,
        )
    finally:
        await lsp_service.shutdown()
    return result


async def test_fake_generic_lsp_go_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "go", "main.go",
        "package main\nfunc main() {}\ntype Example struct {}\nfunc greet() {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "go"
    assert result.language == "go"
    assert result.lsp_language == "go"


async def test_fake_generic_lsp_rust_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "rust", "main.rs",
        "fn main() {}\nstruct Example {}\nfn greet() {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "rust"
    assert result.language == "rust"


async def test_fake_generic_lsp_java_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "java", "Main.java",
        "class Main { public static void main(String[] a) {} }\nclass Example {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "java"
    assert result.language == "java"


async def test_fake_generic_lsp_ruby_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "ruby", "main.rb",
        "def main; end\nclass Example; end\ndef greet; end\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "ruby"
    assert result.language == "ruby"


async def test_fake_generic_lsp_php_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "php", "main.php",
        "<?php\nfunction main() {}\nclass Example {}\nfunction greet() {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "php"
    assert result.language == "php"


async def test_fake_generic_lsp_csharp_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "csharp", "Main.cs",
        "class Main { static void Main() {} }\nclass Example {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"Main", "Example"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "csharp"
    assert result.language == "csharp"


async def test_fake_generic_lsp_kotlin_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "kotlin", "main.kt",
        "fun main() {}\nclass Example\nfun greet() {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "kotlin"
    assert result.language == "kotlin"


async def test_fake_generic_lsp_lua_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "lua", "main.lua",
        "function main() end\nlocal Example = {}\nfunction greet() end\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "lua"
    assert result.language == "lua"


async def test_fake_generic_lsp_clangd_cpp_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "clangd", "main.cpp",
        "int main() { return 0; }\nclass Example {};\nvoid greet() {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "clangd"
    assert result.language == "cpp"


async def test_fake_generic_lsp_clangd_c_returns_real_lsp(monkeypatch, tmp_path) -> None:
    result = await _run_fake_lsp(
        monkeypatch, tmp_path, "clangd", "main.c",
        "int main() { return 0; }\nstruct Example {};\nvoid greet() {}\n",
    )
    names = {s["name"] for s in result.items}
    assert {"main", "Example", "greet"} <= names
    assert result.source == "real_lsp"
    assert result.lsp_server == "clangd"
    assert result.language == "c"


async def test_workspace_root_safety_for_new_language(monkeypatch, tmp_path) -> None:
    settings = _generic_settings(tmp_path, go_enabled=True)
    patch_codeintel_settings(monkeypatch, settings)

    out_of_workspace = tmp_path.parent / "outside_main_lang" / "main.go"
    out_of_workspace.parent.mkdir(parents=True, exist_ok=True)
    out_of_workspace.write_text("package main\n", encoding="utf-8")

    try:
        result = await lsp_service.document_symbols(
            FakeAsyncSession(),
            workspace_id=uuid4(),
            file_path=str(out_of_workspace),
            limit=20,
        )
    except PermissionError:
        await lsp_service.shutdown()
        return
    await lsp_service.shutdown()
    assert result.source == "static_fallback"
