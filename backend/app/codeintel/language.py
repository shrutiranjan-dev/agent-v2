from __future__ import annotations

from pathlib import Path

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".md": "markdown",
    ".mdx": "markdown",
}

LSP_LANGUAGE_ID = {
    "python": "python",
    "typescript": "typescript",
    "typescriptreact": "typescriptreact",
    "javascript": "javascript",
    "javascriptreact": "javascriptreact",
}


def detect_language(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix)


def lsp_language_id(language: str) -> str:
    return LSP_LANGUAGE_ID.get(language, language)


def is_supported_code_file(path: str | Path) -> bool:
    return detect_language(path) is not None
