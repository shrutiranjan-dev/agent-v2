from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.app.codeintel.language import detect_language
from backend.app.core.config import get_settings
from backend.app.core.redaction import redact_text
from backend.app.tools.base import is_inside


def encode_jsonrpc_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


async def read_jsonrpc_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    headers = header_bytes.decode("ascii", errors="replace").split("\r\n")
    content_length = None
    for header in headers:
        if header.lower().startswith("content-length:"):
            content_length = int(header.split(":", 1)[1].strip())
            break
    if content_length is None:
        raise RuntimeError("LSP response missing Content-Length header.")
    payload = await reader.readexactly(content_length)
    return json.loads(payload.decode("utf-8"))


class LspClient:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stdout: asyncio.StreamReader | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._stderr_text = ""
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._workspace_root: Path | None = None
        self._opened_documents: set[str] = set()
        self._diagnostics_by_uri: dict[str, list[dict[str, Any]]] = {}
        self._command: str | None = None
        self._capabilities: dict[str, Any] = {}

    async def health(self, workspace_root: Path) -> dict[str, Any]:
        try:
            await self.initialize(workspace_root)
        except Exception as exc:
            return {
                "status": "failed",
                "command": self._command or get_settings().lsp.python_command,
                "last_error": redact_text(str(exc)),
                "running": False,
            }
        return {
            "status": "ok",
            "command": self._command,
            "last_error": None,
            "running": self._is_running(),
        }

    async def initialize(self, workspace_root: Path) -> dict[str, Any]:
        self._validate_workspace_root(workspace_root)
        async with self._lock:
            if self._is_running() and self._workspace_root == workspace_root:
                return self._capabilities
            await self._restart_locked(workspace_root)
            return self._capabilities

    async def shutdown(self) -> dict[str, Any]:
        async with self._lock:
            await self._shutdown_locked()
        return {"status": "stopped"}

    async def document_symbols(self, path: Path) -> list[dict[str, Any]]:
        payload = await self._request_text_document("textDocument/documentSymbol", path)
        return payload if isinstance(payload, list) else []

    async def goto_definition(self, path: Path, line: int, character: int) -> Any:
        return await self._request_text_document(
            "textDocument/definition",
            path,
            extra={
                "position": {
                    "line": max(line - 1, 0),
                    "character": max(character, 0),
                }
            },
        )

    async def find_references(self, path: Path, line: int, character: int) -> list[dict[str, Any]]:
        payload = await self._request_text_document(
            "textDocument/references",
            path,
            extra={
                "position": {
                    "line": max(line - 1, 0),
                    "character": max(character, 0),
                },
                "context": {"includeDeclaration": True},
            },
        )
        return payload if isinstance(payload, list) else []

    async def diagnostics(self, path: Path) -> list[dict[str, Any]]:
        await self._ensure_document_open(path)
        uri = path.resolve().as_uri()
        return list(self._diagnostics_by_uri.get(uri, []))

    async def _request_text_document(
        self,
        method: str,
        path: Path,
        *,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        await self._ensure_document_open(path)
        params = {"textDocument": {"uri": path.resolve().as_uri()}}
        if extra:
            params.update(extra)
        return await self._request(method, params)

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        settings = get_settings()
        async with self._lock:
            if not self._is_running():
                if self._workspace_root is None:
                    raise RuntimeError("LSP client is not initialized.")
                await self._restart_locked(self._workspace_root)
            self._request_id += 1
            request_id = self._request_id
            await self._write_locked(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            try:
                response = await asyncio.wait_for(
                    self._read_response_locked(request_id),
                    timeout=settings.lsp.request_timeout_seconds,
                )
            except TimeoutError as exc:
                raise TimeoutError(f"LSP request timed out after {settings.lsp.request_timeout_seconds}s: {method}") from exc
            if "error" in response:
                raise RuntimeError(redact_text(json.dumps(response["error"], default=str)))
            result = response.get("result")
            serialized = json.dumps(result, default=str)
            if len(serialized) > settings.lsp.max_response_chars:
                raise RuntimeError(f"LSP response exceeded {settings.lsp.max_response_chars} characters.")
            return result

    async def _restart_locked(self, workspace_root: Path) -> None:
        await self._shutdown_locked()
        command_parts = self._resolve_command(get_settings().lsp.python_command)
        self._command = " ".join(command_parts)
        env = self._build_env()
        self._process = await asyncio.create_subprocess_exec(
            *command_parts,
            cwd=str(workspace_root),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stdout = self._process.stdout
        self._workspace_root = workspace_root
        self._opened_documents.clear()
        self._diagnostics_by_uri.clear()
        self._stderr_text = ""
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(self._capture_stderr(self._process.stderr))
        initialize_params = {
            "processId": None,
            "rootUri": workspace_root.resolve().as_uri(),
            "workspaceFolders": [{"uri": workspace_root.resolve().as_uri(), "name": workspace_root.name or "workspace"}],
            "capabilities": {
                "textDocument": {
                    "definition": {},
                    "references": {},
                    "documentSymbol": {},
                    "publishDiagnostics": {},
                }
            },
            "clientInfo": {"name": "agent-v2", "version": "batch-1"},
        }
        try:
            result = await asyncio.wait_for(
                self._initialize_protocol_locked(initialize_params),
                timeout=get_settings().lsp.startup_timeout_seconds,
            )
        except TimeoutError as exc:
            await self._terminate_locked()
            raise TimeoutError(
                f"LSP startup timed out after {get_settings().lsp.startup_timeout_seconds}s for {self._command}"
            ) from exc
        self._capabilities = result.get("capabilities", {}) if isinstance(result, dict) else {}

    async def _initialize_protocol_locked(self, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        await self._write_locked(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": params,
            }
        )
        response = await self._read_response_locked(request_id)
        await self._write_locked({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        if "error" in response:
            raise RuntimeError(redact_text(json.dumps(response["error"], default=str)))
        return response.get("result") if isinstance(response.get("result"), dict) else {}

    async def _shutdown_locked(self) -> None:
        if not self._process:
            return
        try:
            if self._is_running():
                self._request_id += 1
                request_id = self._request_id
                await self._write_locked({"jsonrpc": "2.0", "id": request_id, "method": "shutdown", "params": {}})
                await asyncio.wait_for(
                    self._read_response_locked(request_id),
                    timeout=get_settings().lsp.shutdown_timeout_seconds,
                )
                await self._write_locked({"jsonrpc": "2.0", "method": "exit", "params": {}})
        except Exception:
            pass
        finally:
            await self._terminate_locked()

    async def _terminate_locked(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=get_settings().lsp.shutdown_timeout_seconds)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._stderr_task:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
        self._process = None
        self._stdout = None
        self._stderr_task = None
        self._workspace_root = None
        self._opened_documents.clear()
        self._diagnostics_by_uri.clear()
        self._capabilities = {}

    async def _write_locked(self, payload: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("LSP process is not available.")
        self._process.stdin.write(encode_jsonrpc_message(payload))
        await self._process.stdin.drain()

    async def _read_response_locked(self, request_id: int) -> dict[str, Any]:
        while True:
            if self._stdout is None:
                raise RuntimeError("LSP stdout stream is unavailable.")
            message = await read_jsonrpc_message(self._stdout)
            method = message.get("method")
            if method == "textDocument/publishDiagnostics":
                params = message.get("params") or {}
                uri = params.get("uri")
                diagnostics = params.get("diagnostics") or []
                if isinstance(uri, str) and isinstance(diagnostics, list):
                    self._diagnostics_by_uri[uri] = diagnostics
                continue
            if message.get("id") == request_id:
                return message

    async def _ensure_document_open(self, path: Path) -> None:
        path = self._validate_document_path(path)
        workspace_root = self._workspace_root or get_settings().lsp.workspace_root
        await self.initialize(workspace_root)
        uri = path.resolve().as_uri()
        async with self._lock:
            if uri in self._opened_documents:
                return
            language_id = detect_language(path.name) or "plaintext"
            text = path.read_text(encoding="utf-8", errors="replace")
            await self._write_locked(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": language_id,
                            "version": 1,
                            "text": text,
                        }
                    },
                }
            )
            self._opened_documents.add(uri)

    def _validate_workspace_root(self, workspace_root: Path) -> None:
        configured_root = get_settings().lsp.workspace_root.resolve()
        resolved = workspace_root.resolve()
        if resolved != configured_root and not is_inside(configured_root, resolved):
            raise PermissionError(f"LSP workspace root is outside configured root: {resolved}")

    def _validate_document_path(self, path: Path) -> Path:
        workspace_root = (self._workspace_root or get_settings().lsp.workspace_root).resolve()
        resolved = path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
        if not is_inside(workspace_root, resolved):
            raise PermissionError(f"LSP document path is outside workspace root: {resolved}")
        if not resolved.exists():
            raise FileNotFoundError(f"LSP document does not exist: {resolved}")
        return resolved

    def _resolve_command(self, command: str) -> list[str]:
        parts = shlex.split(command, posix=os.name != "nt")
        if not parts:
            raise RuntimeError("LSP command is empty.")
        executable = parts[0]
        candidate = Path(executable).expanduser()
        if candidate.is_absolute():
            if not candidate.exists():
                raise RuntimeError(f"LSP command not found: {command}")
            resolved = str(candidate)
        else:
            resolved = shutil.which(executable)
        if not resolved:
            raise RuntimeError(f"LSP command not found: {command}")
        return [resolved, *parts[1:]]

    def _build_env(self) -> dict[str, str]:
        env: dict[str, str] = {"PYTHONUNBUFFERED": "1"}
        for key in ["PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "HOME", "USERPROFILE"]:
            value = os.environ.get(key)
            if value:
                env[key] = value
        return env

    async def _capture_stderr(self, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = redact_text(line.decode("utf-8", errors="replace").rstrip())
            self._stderr_tail.append(text)
            self._stderr_text = "\n".join(self._stderr_tail)

    def _is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def last_error_details(self) -> str | None:
        return self._stderr_text or None

    def resolve_uri_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)

lsp_client = LspClient()
