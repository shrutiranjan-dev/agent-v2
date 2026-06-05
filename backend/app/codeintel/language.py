from __future__ import annotations

from pathlib import Path

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".md": "markdown",
    ".mdx": "markdown",
}


def detect_language(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix)


def is_supported_code_file(path: str | Path) -> bool:
    return detect_language(path) is not None
