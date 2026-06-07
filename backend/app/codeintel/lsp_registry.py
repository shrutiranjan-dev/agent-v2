from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_REAL_LSP = "real_lsp"
SOURCE_STATIC_FALLBACK = "static_fallback"
SOURCE_DISABLED = "static_fallback"
SOURCE_MISSING_COMMAND = "static_fallback"

STATUS_DISABLED = "disabled"
STATUS_MISSING_COMMAND = "missing_command"
STATUS_FAILED = "failed"
STATUS_STATIC_FALLBACK = "static_fallback"


@dataclass
class LspServerPreset:
    server_id: str
    display_name: str
    file_extensions: list[str]
    language_ids: dict[str, str] = field(default_factory=dict)
    default_command: str = ""
    install_hint_windows: str = ""
    install_hint_linux_ci: str = ""
    status: str = "builtin"
    requires_node: bool = False

    @property
    def config_prefix(self) -> str:
        if self.server_id == "python":
            return "python_"
        return f"{self.server_id}_"

    @property
    def languages(self) -> list[str]:
        return list(dict.fromkeys(self.language_ids.values()))


PRESETS: list[LspServerPreset] = [
    LspServerPreset(
        server_id="python",
        display_name="Python LSP",
        file_extensions=[".py", ".pyi"],
        language_ids={".py": "python", ".pyi": "python"},
        default_command="pylsp",
        install_hint_windows="pip install python-lsp-server",
        install_hint_linux_ci="pip install python-lsp-server",
        status="builtin",
    ),
    LspServerPreset(
        server_id="typescript",
        display_name="TypeScript LSP",
        file_extensions=[".ts"],
        language_ids={".ts": "typescript"},
        default_command="typescript-language-server --stdio",
        install_hint_windows="npm install -g typescript-language-server",
        install_hint_linux_ci="npm install -g typescript-language-server",
        status="builtin",
        requires_node=True,
    ),
    LspServerPreset(
        server_id="typescriptreact",
        display_name="TypeScript React LSP",
        file_extensions=[".tsx"],
        language_ids={".tsx": "typescriptreact"},
        default_command="typescript-language-server --stdio",
        install_hint_windows="npm install -g typescript-language-server",
        install_hint_linux_ci="npm install -g typescript-language-server",
        status="builtin",
        requires_node=True,
    ),
    LspServerPreset(
        server_id="javascript",
        display_name="JavaScript LSP",
        file_extensions=[".js", ".mjs", ".cjs"],
        language_ids={".js": "javascript", ".mjs": "javascript", ".cjs": "javascript"},
        default_command="typescript-language-server --stdio",
        install_hint_windows="npm install -g typescript-language-server",
        install_hint_linux_ci="npm install -g typescript-language-server",
        status="builtin",
        requires_node=True,
    ),
    LspServerPreset(
        server_id="javascriptreact",
        display_name="JavaScript React LSP",
        file_extensions=[".jsx"],
        language_ids={".jsx": "javascriptreact"},
        default_command="typescript-language-server --stdio",
        install_hint_windows="npm install -g typescript-language-server",
        install_hint_linux_ci="npm install -g typescript-language-server",
        status="builtin",
        requires_node=True,
    ),
    LspServerPreset(
        server_id="go",
        display_name="Go LSP",
        file_extensions=[".go"],
        language_ids={".go": "go"},
        default_command="gopls",
        install_hint_windows="go install golang.org/x/tools/gopls@latest",
        install_hint_linux_ci="go install golang.org/x/tools/gopls@latest",
        status="preset",
    ),
    LspServerPreset(
        server_id="rust",
        display_name="Rust LSP",
        file_extensions=[".rs"],
        language_ids={".rs": "rust"},
        default_command="rust-analyzer",
        install_hint_windows="rustup component add rust-analyzer",
        install_hint_linux_ci="rustup component add rust-analyzer",
        status="preset",
    ),
    LspServerPreset(
        server_id="java",
        display_name="Java LSP",
        file_extensions=[".java"],
        language_ids={".java": "java"},
        default_command="jdtls",
        install_hint_windows="Install Eclipse JDT LS from https://download.eclipse.org/jdtls/",
        install_hint_linux_ci="Install Eclipse JDT LS from https://download.eclipse.org/jdtls/",
        status="preset",
    ),
    LspServerPreset(
        server_id="ruby",
        display_name="Ruby LSP",
        file_extensions=[".rb"],
        language_ids={".rb": "ruby"},
        default_command="ruby-lsp",
        install_hint_windows="gem install ruby-lsp",
        install_hint_linux_ci="gem install ruby-lsp",
        status="preset",
    ),
    LspServerPreset(
        server_id="php",
        display_name="PHP LSP",
        file_extensions=[".php"],
        language_ids={".php": "php"},
        default_command="intelephense --stdio",
        install_hint_windows="npm install -g intelephense",
        install_hint_linux_ci="npm install -g intelephense",
        status="preset",
    ),
    LspServerPreset(
        server_id="csharp",
        display_name="C# LSP",
        file_extensions=[".cs"],
        language_ids={".cs": "csharp"},
        default_command="csharp-ls",
        install_hint_windows="Install csharp-ls from https://github.com/razzmatazz/csharp-language-server",
        install_hint_linux_ci="Install csharp-ls from https://github.com/razzmatazz/csharp-language-server",
        status="preset",
    ),
    LspServerPreset(
        server_id="kotlin",
        display_name="Kotlin LSP",
        file_extensions=[".kt", ".kts"],
        language_ids={".kt": "kotlin", ".kts": "kotlin"},
        default_command="kotlin-language-server",
        install_hint_windows="Install kotlin-language-server from GitHub releases",
        install_hint_linux_ci="Install kotlin-language-server from GitHub releases",
        status="preset",
    ),
    LspServerPreset(
        server_id="lua",
        display_name="Lua LSP",
        file_extensions=[".lua"],
        language_ids={".lua": "lua"},
        default_command="lua-language-server",
        install_hint_windows="Install lua-language-server from https://github.com/LuaLS/lua-language-server",
        install_hint_linux_ci="Install lua-language-server from https://github.com/LuaLS/lua-language-server",
        status="preset",
    ),
    LspServerPreset(
        server_id="clangd",
        display_name="C/C++ LSP",
        file_extensions=[".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"],
        language_ids={
            ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".h": "c", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
        },
        default_command="clangd",
        install_hint_windows="Install clangd from https://clangd.llvm.org/installation.html",
        install_hint_linux_ci="apt-get install clangd or install from https://clangd.llvm.org/",
        status="preset",
    ),
]

_server_by_id: dict[str, LspServerPreset] = {p.server_id: p for p in PRESETS}
_server_by_ext: dict[str, LspServerPreset] = {}
_server_by_language: dict[str, LspServerPreset] = {}
_language_id_by_lang: dict[str, str] = {}
_extension_by_lang: dict[str, str] = {}
_all_file_extensions: set[str] = set()

for _preset in PRESETS:
    for _ext in _preset.file_extensions:
        _server_by_ext[_ext] = _preset
        _all_file_extensions.add(_ext)
    for _ext, _lid in _preset.language_ids.items():
        _language_id_by_lang[_lid] = _lid
        _server_by_language[_lid] = _preset
    for _ext in _preset.file_extensions:
        _extension_by_lang[_ext] = _preset.language_ids.get(_ext, _preset.server_id)

EXTENSION_BY_LANGUAGE = dict(_extension_by_lang)
LANGUAGE_ID_MAP = dict(_language_id_by_lang)
ALL_FILE_EXTENSIONS = frozenset(_all_file_extensions)


def get_preset_for_language(language: str) -> LspServerPreset | None:
    return _server_by_language.get(language)


def get_preset(server_id: str) -> LspServerPreset | None:
    return _server_by_id.get(server_id)


def get_preset_for_file(path: str | Path) -> LspServerPreset | None:
    suffix = Path(path).suffix.lower()
    return _server_by_ext.get(suffix)


_AUX_LANGUAGE_BY_EXT: dict[str, str] = {
    ".md": "markdown",
    ".mdx": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".txt": "text",
}


def detect_language(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    preset = _server_by_ext.get(suffix)
    if preset:
        return preset.language_ids.get(suffix, preset.server_id)
    return _AUX_LANGUAGE_BY_EXT.get(suffix)


def is_supported_code_file(path: str | Path) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in _all_file_extensions


def lsp_language_id(language: str) -> str:
    return _language_id_by_lang.get(language, language)


def get_server_attribute(lsp_config: Any, server_id: str, attr: str) -> Any:
    """Look up a per-server attribute on an LspConfig (or SimpleNamespace mock)."""
    if lsp_config is None:
        return None
    getter = getattr(lsp_config, "get_for_server", None)
    if callable(getter):
        try:
            return getter(server_id, attr)
        except Exception:
            return None
    getter = getattr(lsp_config, "get_for_language", None)
    if callable(getter):
        try:
            return getter(server_id, attr)
        except Exception:
            return None
    if server_id == "python":
        field_name = "python_command" if attr == "command" else attr
    else:
        prefix = f"{server_id}_"
        candidate = f"{prefix}{attr}"
        if hasattr(lsp_config, candidate):
            field_name = candidate
        elif server_id in ("typescript", "typescriptreact", "javascript", "javascriptreact") and hasattr(lsp_config, f"ts_{attr}"):
            field_name = f"ts_{attr}"
        else:
            field_name = attr
    return getattr(lsp_config, field_name, None)


def all_server_ids() -> list[str]:
    return [p.server_id for p in PRESETS]


def ts_language_ids() -> set[str]:
    return {"typescript", "typescriptreact", "javascript", "javascriptreact"}


def python_language_ids() -> set[str]:
    return {"python"}


def should_use_ts_config_prefix(language: str) -> bool:
    return language in ts_language_ids()
