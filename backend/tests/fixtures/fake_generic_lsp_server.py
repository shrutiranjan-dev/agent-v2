from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def _resolve_language() -> str:
    for arg in sys.argv[1:]:
        if arg.startswith("--language="):
            return arg.split("=", 1)[1].lower()
    return os.environ.get("FAKE_LSP_LANGUAGE", "generic").lower()


def read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()
    content_length = int(headers["content-length"])
    payload = sys.stdin.buffer.read(content_length)
    return json.loads(payload.decode("utf-8"))


def write_message(payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def relative_path(uri: str) -> str:
    path = Path(unquote(urlparse(uri).path))
    return path.name


LANGUAGE = _resolve_language()


SYMBOLS_BY_LANGUAGE = {
    "go": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 5}, "end": {"line": 0, "character": 9}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 5}, "end": {"line": 9, "character": 10}},
        },
    ],
    "rust": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 7}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 3}, "end": {"line": 9, "character": 8}},
        },
    ],
    "java": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 9}, "end": {"line": 0, "character": 13}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 13}, "end": {"line": 4, "character": 20}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 9}, "end": {"line": 9, "character": 14}},
        },
    ],
    "ruby": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 7}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 3}, "end": {"line": 9, "character": 8}},
        },
    ],
    "php": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 7}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 3}, "end": {"line": 9, "character": 8}},
        },
    ],
    "csharp": [
        {
            "name": "Main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 16}, "end": {"line": 0, "character": 20}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 13}, "end": {"line": 4, "character": 20}},
        },
        {
            "name": "Greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 16}, "end": {"line": 9, "character": 21}},
        },
    ],
    "kotlin": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 8}, "end": {"line": 0, "character": 12}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 8}, "end": {"line": 9, "character": 13}},
        },
    ],
    "lua": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 7}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 3}, "end": {"line": 9, "character": 8}},
        },
    ],
    "c": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 8}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 4}, "end": {"line": 9, "character": 9}},
        },
    ],
    "cpp": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 8}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 4}, "end": {"line": 9, "character": 9}},
        },
    ],
    "generic": [
        {
            "name": "main",
            "kind": 12,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            "selectionRange": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 7}},
        },
        {
            "name": "Example",
            "kind": 5,
            "range": {"start": {"line": 4, "character": 0}, "end": {"line": 7, "character": 1}},
            "selectionRange": {"start": {"line": 4, "character": 6}, "end": {"line": 4, "character": 13}},
        },
        {
            "name": "greet",
            "kind": 12,
            "range": {"start": {"line": 9, "character": 0}, "end": {"line": 11, "character": 1}},
            "selectionRange": {"start": {"line": 9, "character": 3}, "end": {"line": 9, "character": 8}},
        },
    ],
}


def publish_diagnostics(uri: str) -> None:
    write_message(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": uri,
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 8},
                        },
                        "severity": 2,
                        "code": f"{LANGUAGE.upper()}001",
                        "message": f"fake {LANGUAGE} warning",
                    }
                ],
            },
        }
    )


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        method = message.get("method")
        params = message.get("params") or {}
        request_id = message.get("id")
        if method == "initialize":
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "capabilities": {
                            "definitionProvider": True,
                            "referencesProvider": True,
                            "documentSymbolProvider": True,
                        }
                    },
                }
            )
        elif method == "initialized":
            continue
        elif method == "shutdown":
            write_message({"jsonrpc": "2.0", "id": request_id, "result": None})
        elif method == "exit":
            return 0
        elif method == "textDocument/didOpen":
            uri = params["textDocument"]["uri"]
            publish_diagnostics(uri)
        elif method == "textDocument/documentSymbol":
            uri = params["textDocument"]["uri"]
            file_name = relative_path(uri)
            if "timeout" in file_name:
                continue
            symbols = SYMBOLS_BY_LANGUAGE.get(LANGUAGE, SYMBOLS_BY_LANGUAGE["generic"])
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": symbols,
                }
            )
        elif method == "textDocument/definition":
            uri = params["textDocument"]["uri"]
            symbols = SYMBOLS_BY_LANGUAGE.get(LANGUAGE, SYMBOLS_BY_LANGUAGE["generic"])
            first = symbols[0]
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "uri": uri,
                        "range": first["selectionRange"],
                    },
                }
            )
        elif method == "textDocument/references":
            uri = params["textDocument"]["uri"]
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": [
                        {
                            "uri": uri,
                            "range": {
                                "start": {"line": 3, "character": 4},
                                "end": {"line": 3, "character": 9},
                            },
                        },
                        {
                            "uri": uri,
                            "range": {
                                "start": {"line": 5, "character": 8},
                                "end": {"line": 5, "character": 13},
                            },
                        },
                    ],
                }
            )
        else:
            write_message({"jsonrpc": "2.0", "id": request_id, "result": None})


if __name__ == "__main__":
    raise SystemExit(main())
