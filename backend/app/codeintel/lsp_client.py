from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import platform
import shlex
import shutil
import sys
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.app.codeintel.language import detect_language, lsp_language_id
from backend.app.codeintel.lsp_registry import (
    all_server_ids,
    get_preset,
    get_preset_for_language,
    get_server_attribute,
)
from backend.app.core.config import get_settings
from backend.app.core.redaction import redact_text
from backend.app.tools.base import is_inside


def parse_lsp_command(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        parts = [str(part) for part in command if str(part).strip()]
        if not parts:
            raise RuntimeError("LSP command is empty.")
        return parts
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        raise RuntimeError(f"Invalid LSP command: {command}") from exc
    parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"} else part for part in parts]
    if not parts:
        raise RuntimeError("LSP command is empty.")
    return parts


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
    def __init__(self, language: str = "python") -> None:
        self._language = language
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
        self._configured_command: str | None = None
        self._spawn_argv: list[str] = []
        self._spawn_debug: dict[str, Any] = {}

    @property
    def language(self) -> str:
        return self._language

    def _get_settings_attr(self, attr: str) -> Any:
        preset = get_preset_for_language(self._language)
        if preset is not None:
            return get_server_attribute(get_settings().lsp, preset.server_id, attr)
        return get_server_attribute(get_settings().lsp, self._language, attr)

    async def health(self, workspace_root: Path) -> dict[str, Any]:
        try:
            await self.initialize(workspace_root)
        except Exception as exc:
            return {
                "status": "failed",
                "command": self._command or self._get_settings_attr("command"),
                "last_error": redact_text(str(exc)),
                "running": False,
                "debug": self.debug_snapshot(error=exc),
            }
        return {
            "status": "ok",
            "command": self._command,
            "last_error": None,
            "running": self._is_running(),
            "debug": self.debug_snapshot(),
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
                    timeout=self._get_settings_attr("request_timeout_seconds"),
                )
            except TimeoutError as exc:
                raise TimeoutError(f"LSP request timed out after {self._get_settings_attr('request_timeout_seconds')}s: {method}") from exc
            if "error" in response:
                raise RuntimeError(redact_text(json.dumps(response["error"], default=str)))
            result = response.get("result")
            serialized = json.dumps(result, default=str)
            if len(serialized) > self._get_settings_attr("max_response_chars"):
                raise RuntimeError(f"LSP response exceeded {self._get_settings_attr('max_response_chars')} characters.")
            return result

    async def _restart_locked(self, workspace_root: Path) -> None:
        await self._shutdown_locked()
        self._configured_command = self._get_settings_attr("command")
        try:
            command_info = self._resolve_command(self._configured_command)
        except Exception as exc:
            self._spawn_argv = []
            self._command = str(self._configured_command)
            self._spawn_debug = {
                "configured_command": self._configured_command,
                "spawn_argv": [],
                "executable": None,
                "resolved_executable": None,
                "command_exists": False,
                "script_path": None,
                "script_exists": None,
                "cwd": str(workspace_root),
                "workspace_root": str(workspace_root.resolve()),
                "path": os.environ.get("PATH"),
                "last_error_type": type(exc).__name__,
                "last_error": redact_text(str(exc)),
            }
            raise
        spawn_argv = command_info["spawn_argv"]
        self._spawn_argv = list(spawn_argv)
        self._command = " ".join(spawn_argv) if spawn_argv else str(self._configured_command)
        env = self._build_env()
        self._spawn_debug = {
            "configured_command": self._configured_command,
            "spawn_argv": list(spawn_argv),
            "executable": command_info["executable"],
            "resolved_executable": command_info["resolved_executable"],
            "command_exists": command_info["command_exists"],
            "script_path": command_info["script_path"],
            "script_exists": command_info["script_exists"],
            "cwd": str(workspace_root),
            "workspace_root": str(workspace_root.resolve()),
            "path": env.get("PATH"),
        }
        if not command_info["command_exists"]:
            self._spawn_debug["last_error_type"] = "RuntimeError"
            self._spawn_debug["last_error"] = redact_text(str(command_info["error"]))
            raise RuntimeError(str(command_info["error"]))
        try:
            self._process = await asyncio.create_subprocess_exec(
                *spawn_argv,
                cwd=str(workspace_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            self._spawn_debug["last_error_type"] = type(exc).__name__
            self._spawn_debug["last_error"] = redact_text(str(exc))
            raise
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
                timeout=self._get_settings_attr("startup_timeout_seconds"),
            )
        except TimeoutError as exc:
            await self._terminate_locked()
            raise TimeoutError(
                f"LSP startup timed out after {self._get_settings_attr('startup_timeout_seconds')}s for {self._command}"
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
                    timeout=self._get_settings_attr("shutdown_timeout_seconds"),
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
        workspace_root = self._workspace_root or self._get_workspace_root()
        await self.initialize(workspace_root)
        uri = path.resolve().as_uri()
        async with self._lock:
            if uri in self._opened_documents:
                return
            language_id = lsp_language_id(detect_language(path.name) or "plaintext")
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
        configured_root = self._get_workspace_root().resolve()
        resolved = workspace_root.resolve()
        if resolved != configured_root and not is_inside(configured_root, resolved):
            raise PermissionError(f"LSP workspace root is outside configured root: {resolved}")

    def _validate_document_path(self, path: Path) -> Path:
        default_root = self._get_workspace_root()
        workspace_root = (self._workspace_root or default_root).resolve()
        resolved = path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
        if not is_inside(workspace_root, resolved):
            raise PermissionError(f"LSP document path is outside workspace root: {resolved}")
        if not resolved.exists():
            raise FileNotFoundError(f"LSP document does not exist: {resolved}")
        return resolved

    def _resolve_command(self, command: str | list[str]) -> dict[str, Any]:
        parts = parse_lsp_command(command)
        executable = parts[0]
        candidate = Path(executable).expanduser()
        resolved_executable: str | None = None
        if candidate.is_absolute() or candidate.parent != Path("."):
            if candidate.exists():
                resolved_executable = str(candidate)
        else:
            resolved_executable = shutil.which(executable)
        script_path, script_exists = self._detect_script_path(parts)
        return {
            "configured_command": command if isinstance(command, str) else " ".join(parts),
            "spawn_argv": ([resolved_executable, *parts[1:]] if resolved_executable else list(parts)),
            "executable": executable,
            "resolved_executable": resolved_executable,
            "command_exists": resolved_executable is not None,
            "script_path": script_path,
            "script_exists": script_exists,
            "error": None if resolved_executable else RuntimeError(f"LSP command not found: {executable}"),
        }

    def _build_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in [
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "TMP",
            "TEMP",
            "SYSTEMROOT",
            "WINDIR",
            "PATHEXT",
            "USERPROFILE",
            "PYTHONPATH",
            "LD_LIBRARY_PATH",
            "VIRTUAL_ENV",
        ]:
            value = os.environ.get(key)
            if value:
                env[key] = value
        preset = get_preset_for_language(self._language)
        if preset is not None and preset.requires_node:
            node_path = shutil.which("node")
            npm_path = shutil.which("npm") or shutil.which("npm.cmd")
            npx_path = shutil.which("npx") or shutil.which("npx.cmd")
            if node_path:
                env["NODE_PATH"] = str(Path(node_path).parent)
            if npm_path:
                env["NPM_PATH"] = str(Path(npm_path).parent)
            if npx_path:
                env["NPX_PATH"] = str(Path(npx_path).parent)
        env["PYTHONUNBUFFERED"] = "1"
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

    def debug_snapshot(self, *, error: Exception | None = None) -> dict[str, Any]:
        preset = get_preset_for_language(self._language)
        import_module = None
        if preset is not None:
            first_part = parse_lsp_command(preset.default_command)[0] if preset.default_command else ""
            first_base = Path(first_part).name
            if first_base and "." not in first_base:
                import_module = first_base.replace("-", "_")
        spec = importlib.util.find_spec(import_module) if import_module else None
        lang_import_check = {
            "module": import_module,
            "available": spec is not None,
            "origin": getattr(spec, "origin", None) if spec else None,
        }
        snapshot = {
            "language": self._language,
            "server_id": preset.server_id if preset else None,
            "display_name": preset.display_name if preset else None,
            "install_hint_windows": preset.install_hint_windows if preset else None,
            "install_hint_linux_ci": preset.install_hint_linux_ci if preset else None,
            "configured_command": self._configured_command or self._get_settings_attr("command"),
            "spawn_argv": list(self._spawn_argv),
            "command": self._command or self._get_settings_attr("command"),
            "executable": self._spawn_debug.get("executable"),
            "resolved_executable": self._spawn_debug.get("resolved_executable"),
            "command_exists": bool(self._spawn_debug.get("command_exists")),
            "script_path": self._spawn_debug.get("script_path"),
            "script_exists": self._spawn_debug.get("script_exists"),
            "cwd": self._spawn_debug.get("cwd"),
            "workspace_root": self._spawn_debug.get("workspace_root")
            or str(self._get_workspace_root().resolve()),
            "path": self._spawn_debug.get("path") or os.environ.get("PATH"),
            "python_executable": shutil.which("python"),
            "python3_executable": shutil.which("python3"),
            "sys_executable": sys.executable,
            "platform": platform.platform(),
            "language_server_import_check": lang_import_check,
            "node_check": self._node_check() if (preset is not None and preset.requires_node) else None,
            "stderr_tail": self.last_error_details(),
            "running": self._is_running(),
        }
        if error is not None:
            snapshot["last_error_type"] = type(error).__name__
            snapshot["last_error"] = redact_text(str(error))
        elif self._spawn_debug.get("last_error"):
            snapshot["last_error_type"] = self._spawn_debug.get("last_error_type")
            snapshot["last_error"] = self._spawn_debug.get("last_error")
        return snapshot

    def _get_workspace_root(self) -> Path:
        ws_attr = self._get_settings_attr("workspace_root")
        if ws_attr:
            return ws_attr
        return get_settings().lsp.workspace_root

    def _node_check(self) -> dict[str, Any] | None:
        node_version = None
        npm_version = None
        tsls_version = None
        try:
            import subprocess
            node_result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=2)
            if node_result.returncode == 0:
                node_version = node_result.stdout.strip()
            npm_result = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=2)
            if npm_result.returncode == 0:
                npm_version = npm_result.stdout.strip()
            tsls_result = subprocess.run(["typescript-language-server", "--version"], capture_output=True, text=True, timeout=2)
            if tsls_result.returncode == 0:
                tsls_version = tsls_version = tsls_result.stdout.strip()
        except Exception:
            pass
        return {
            "node_version": node_version,
            "npm_version": npm_version,
            "typescript_language_server_version": tsls_version,
        }

    def _detect_script_path(self, parts: list[str]) -> tuple[str | None, bool | None]:
        if len(parts) < 2:
            return None, None
        candidate = parts[1]
        if not candidate:
            return None, None
        looks_like_path = (
            "/" in candidate
            or "\\" in candidate
            or candidate.startswith(".")
            or Path(candidate).suffix.lower() in {".sh", ".ps1", ".cmd", ".bat", ".py"}
        )
        if not looks_like_path:
            return None, None
        script_path = str(Path(candidate).expanduser())
        return script_path, Path(candidate).expanduser().exists()

    def resolve_uri_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)


class MultiLanguageLspClient:
    def __init__(self) -> None:
        self._clients: dict[str, LspClient] = {}
        for server_id in all_server_ids():
            preset = get_preset(server_id)
            if preset is None:
                continue
            for language in preset.languages:
                if language not in self._clients:
                    self._clients[language] = LspClient(language)

    def get_client(self, language: str) -> LspClient | None:
        return self._clients.get(language)

    def languages(self) -> list[str]:
        return list(self._clients.keys())

    async def health(self, workspace_root: Path) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for server_id in all_server_ids():
            preset = get_preset(server_id)
            if preset is None:
                continue
            client = self._clients.get(preset.languages[0])
            if client is None:
                continue
            snapshot[server_id] = await client.health(workspace_root)
        return snapshot

    async def shutdown_all(self) -> dict[str, Any]:
        results = {}
        for server_id in all_server_ids():
            preset = get_preset(server_id)
            if preset is None:
                continue
            client = self._clients.get(preset.languages[0])
            if client is None:
                continue
            try:
                results[server_id] = await client.shutdown()
            except Exception as exc:
                results[server_id] = {"error": str(exc)}
        return results

    def debug_snapshot_all(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for server_id in all_server_ids():
            preset = get_preset(server_id)
            if preset is None:
                continue
            client = self._clients.get(preset.languages[0])
            if client is None:
                continue
            snapshot[server_id] = client.debug_snapshot()
        return snapshot


multi_lsp_client = MultiLanguageLspClient()
lsp_client = multi_lsp_client._clients.get("python") or LspClient("python")
