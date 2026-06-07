from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.app.cli.config import CliConfig


class CliApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentApiClient(AbstractContextManager["AgentApiClient"]):
    def __init__(self, config: CliConfig, *, client: httpx.Client | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=config.base_url, timeout=config.timeout_seconds)

    def __enter__(self) -> AgentApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._owns_client:
            self._client.close()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def list_agents(self, *, include_hidden: bool = True) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/agents?include_hidden={str(include_hidden).lower()}")
        return list(payload.get("agents", []))

    def create_session(
        self,
        *,
        title: str | None = None,
        agent_id: str = "build",
        model_name: str | None = None,
    ) -> dict[str, Any]:
        body = {"title": title, "agent_id": agent_id, "model_name": model_name}
        payload = self._request("POST", "/sessions", json={k: v for k, v in body.items() if v is not None})
        return dict(payload["session"])

    def list_sessions(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/sessions")
        return list(payload.get("sessions", []))

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}")

    def send_message(
        self,
        session_id: str,
        *,
        content: str,
        agent_id: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        body = {"content": content, "agent_id": agent_id, "model_name": model_name}
        return self._request(
            "POST",
            f"/sessions/{session_id}/messages",
            json={k: v for k, v in body.items() if v is not None},
        )

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/sessions/{session_id}/events")
        return list(payload.get("events", []))

    def list_permissions(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        query = f"?{urlencode({'session_id': session_id})}" if session_id else ""
        payload = self._request("GET", f"/permissions{query}")
        return list(payload.get("permissions", []))

    def approve_permission(self, permission_id: str, *, message: str | None = None) -> dict[str, Any]:
        return self._request("POST", f"/permissions/{permission_id}/approve", json={"message": message})

    def deny_permission(self, permission_id: str, *, message: str | None = None) -> dict[str, Any]:
        return self._request("POST", f"/permissions/{permission_id}/deny", json={"message": message})

    def list_human_input_requests(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {k: v for k, v in {"session_id": session_id, "status": status}.items() if v}
        query = f"?{urlencode(params)}" if params else ""
        payload = self._request("GET", f"/human-input/requests{query}")
        return list(payload.get("requests", []))

    def answer_human_input(self, request_id: str, *, answer: str) -> dict[str, Any]:
        return self._request("POST", f"/human-input/{request_id}/answer", json={"answer": answer})

    def cancel_human_input(self, request_id: str, *, message: str | None = None) -> dict[str, Any]:
        return self._request("POST", f"/human-input/{request_id}/cancel", json={"message": message})

    def list_queue_jobs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if session_id:
            params["session_id"] = session_id
        payload = self._request("GET", f"/queue/jobs?{urlencode(params)}")
        return list(payload.get("jobs", []))

    def queue_stats(self) -> dict[str, Any]:
        return self._request("GET", "/queue/stats")

    def get_queue_job(self, queue_job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/queue/jobs/{queue_job_id}").get("job", {})

    def retry_queue_job(self, queue_job_id: str, *, reason: str = "cli_retry") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/queue/jobs/{queue_job_id}/retry",
            json={"reason": reason, "publish": True},
        ).get("job", {})

    def cancel_queue_job(self, queue_job_id: str, *, reason: str = "cli_cancel") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/queue/jobs/{queue_job_id}/cancel",
            json={"reason": reason, "publish": True},
        ).get("job", {})

    def list_artifacts(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        path = f"/sessions/{session_id}/artifacts" if session_id else "/artifacts"
        payload = self._request("GET", path)
        return list(payload.get("artifacts", []))

    def list_file_changes(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        path: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if session_id:
            params["session_id"] = session_id
        if run_id:
            params["run_id"] = run_id
        if path:
            params["path"] = path
        payload = self._request("GET", f"/file-changes?{urlencode(params)}")
        return list(payload.get("file_changes", []))

    def get_file_change(
        self,
        file_change_id: str,
        *,
        include_content: bool = True,
    ) -> dict[str, Any]:
        params = urlencode({"include_content": str(include_content).lower()})
        payload = self._request("GET", f"/file-changes/{file_change_id}?{params}")
        return dict(payload.get("file_change", {}))

    def revert_file_change(
        self,
        file_change_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        payload = self._request(
            "POST",
            f"/file-changes/{file_change_id}/revert",
            json={"force": force},
        )
        return dict(payload.get("file_change", {}))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CliApiError(_safe_error(exc.response), status_code=exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise CliApiError(f"Backend unavailable at {self.config.base_url}: {exc.__class__.__name__}") from exc
        data = response.json()
        return dict(data) if isinstance(data, dict) else {"data": data}


def _safe_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = response.text
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or response.reason_phrase
    else:
        detail = data or response.reason_phrase
    return f"HTTP {response.status_code}: {detail}"


def api_client(config: CliConfig) -> Iterator[AgentApiClient]:
    with AgentApiClient(config) as client:
        yield client
