from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


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
                        "code": "TS001",
                        "message": "fake typescript warning",
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
            if "sleep" in file_name:
                import time
                time.sleep(2)
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": [
                        {
                            "name": "greet",
                            "kind": 12,
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 2, "character": 1},
                            },
                            "selectionRange": {
                                "start": {"line": 0, "character": 9},
                                "end": {"line": 0, "character": 14},
                            },
                        },
                        {
                            "name": "Greeter",
                            "kind": 5,
                            "range": {
                                "start": {"line": 4, "character": 0},
                                "end": {"line": 7, "character": 1},
                            },
                            "selectionRange": {
                                "start": {"line": 4, "character": 6},
                                "end": {"line": 4, "character": 13},
                            },
                        },
                    ],
                }
            )
        elif method == "textDocument/definition":
            uri = params["textDocument"]["uri"]
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "uri": uri,
                        "range": {
                            "start": {"line": 0, "character": 9},
                            "end": {"line": 0, "character": 14},
                        },
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
