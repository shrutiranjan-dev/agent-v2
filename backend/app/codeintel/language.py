from __future__ import annotations

from backend.app.codeintel.lsp_registry import (
    detect_language,
    is_supported_code_file,
    lsp_language_id,
)

__all__ = [
    "LANGUAGE_BY_EXTENSION",
    "LSP_LANGUAGE_ID",
    "detect_language",
    "is_supported_code_file",
    "lsp_language_id",
]

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
