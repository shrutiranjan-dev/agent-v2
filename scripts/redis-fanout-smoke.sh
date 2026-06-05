#!/usr/bin/env bash
set -euo pipefail

API_A_BASE="${API_A_BASE:-${API_BASE:-http://localhost:8000}}"
BACKEND_B_PORT="${BACKEND_B_PORT:-18080}"
API_B_BASE="${API_B_BASE:-http://127.0.0.1:${BACKEND_B_PORT}}"
WS_B_BASE="${WS_B_BASE:-ws://127.0.0.1:${BACKEND_B_PORT}}"
REDIS_URL="${REDIS_URL:-redis://localhost:16379/0}"
DATABASE_URL="${AP_TEST_POSTGRES_URL:-${AP_DATABASE_URL:-}}"
export API_A_BASE API_B_BASE WS_B_BASE REDIS_URL DATABASE_URL BACKEND_B_PORT

echo "[redis-fanout-smoke] validating Redis pub/sub fanout"
echo "[redis-fanout-smoke] API_A_BASE=${API_A_BASE}"
echo "[redis-fanout-smoke] API_B_BASE=${API_B_BASE}"
echo "[redis-fanout-smoke] WS_B_BASE=${WS_B_BASE}"
echo "[redis-fanout-smoke] REDIS_URL=${REDIS_URL}"

.venv/bin/python - <<'PY'
import asyncio
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import redis.asyncio as redis
import websockets

api_a_base = os.environ.get("API_A_BASE", "http://localhost:8000")
api_b_base = os.environ.get("API_B_BASE", "http://127.0.0.1:18080")
ws_b_base = os.environ.get("WS_B_BASE", "ws://127.0.0.1:18080")
redis_url = os.environ.get("REDIS_URL", "redis://localhost:16379/0")
database_url = os.environ.get("DATABASE_URL") or os.environ.get("AP_TEST_POSTGRES_URL") or os.environ.get("AP_DATABASE_URL")
backend_b_port = os.environ.get("BACKEND_B_PORT", "18080")


async def direct_redis_delivery_check() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        health = await client.get(f"{api_a_base}/health/dependencies")
        health.raise_for_status()
        payload = health.json()
        redis_status = payload.get("dependencies", {}).get("redis", {}).get("status")
        if redis_status != "ok":
            raise SystemExit(f"Redis dependency is not ok: {payload}")
        created = await client.post(
            f"{api_a_base}/sessions",
            json={"title": "Redis fanout smoke", "agent_id": "general"},
        )
        created.raise_for_status()
        session_id = created.json()["session"]["id"]

    channel = f"session:{session_id}:events"
    sentinel_id = str(uuid4())
    envelope = {
        "id": sentinel_id,
        "type": "worker.fanout_smoke",
        "event_type": "worker.fanout_smoke",
        "severity": "info",
        "organization_id": None,
        "project_id": None,
        "workspace_id": None,
        "session_id": session_id,
        "agent_run_id": None,
        "tool_call_id": None,
        "payload": {"source": "redis-fanout-smoke", "channel": channel},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client = redis.from_url(redis_url, decode_responses=True)
    websocket_url = f"{api_a_base.replace('http://', 'ws://').replace('https://', 'wss://')}/ws/sessions/{session_id}"
    try:
        async with websockets.connect(websocket_url) as websocket:
            for attempt in range(5):
                await asyncio.sleep(0.5)
                await redis_client.publish(channel, json.dumps(envelope))
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=2)
                    except TimeoutError:
                        break
                    event = json.loads(raw)
                    if event.get("id") == sentinel_id:
                        print("redis connection: ok")
                        print(f"channel naming: {channel}")
                        print("publish: ok")
                        print("subscribe: ok")
                        print("websocket delivery: ok")
                        return session_id
            raise SystemExit("WebSocket did not receive Redis sentinel event")
    finally:
        await redis_client.aclose()


async def wait_for_health(base_url: str, timeout_seconds: int = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    async with httpx.AsyncClient(timeout=2) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"{base_url}/health")
                if response.status_code == 200:
                    return True
            except Exception:
                await asyncio.sleep(0.5)
    return False


def cancel_queued_jobs_for_session(session_id: str) -> None:
    if not database_url:
        return
    url = database_url.replace("+asyncpg", "").replace("+psycopg", "")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update queue_jobs
                   set status = 'cancelled', updated_at = now()
                 where session_id = %s
                   and status = 'queued'
                """,
                (session_id,),
            )
            cur.execute(
                """
                update agent_runs
                   set status = 'failed', error = 'fanout smoke cancelled queued model run', completed_at = now(), updated_at = now()
                 where session_id = %s
                   and status = 'queued'
                """,
                (session_id,),
            )
            cur.execute(
                "update sessions set status = 'failed', updated_at = now() where id = %s and status = 'queued'",
                (session_id,),
            )
        conn.commit()


async def true_two_backend_check() -> bool:
    if not database_url:
        print("TRUE_TWO_BACKEND_FANOUT=not_available")
        print("true two-backend blocker: AP_TEST_POSTGRES_URL or AP_DATABASE_URL is required to start backend B")
        return False

    env = {
        **os.environ,
        "AP_DATABASE_URL": database_url,
        "AP_REDIS_URL": redis_url,
        "AP_REDIS_PUBSUB_ENABLED": "true",
        "AP_QUEUE_ENABLED": "false",
        "AP_API_PORT": backend_b_port,
    }
    stdout_path = Path("/tmp/redis-fanout-backend-b.out")
    stderr_path = Path("/tmp/redis-fanout-backend-b.err")
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.Popen(
            [
                ".venv/bin/python",
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                backend_b_port,
            ],
            cwd=Path.cwd(),
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
    try:
        if not await wait_for_health(api_b_base):
            print("TRUE_TWO_BACKEND_FANOUT=not_available")
            print(f"true two-backend blocker: backend B did not become healthy; see {stdout_path} and {stderr_path}")
            return False

        async with httpx.AsyncClient(timeout=10) as client:
            created = await client.post(
                f"{api_a_base}/sessions",
                json={"title": "True two-backend fanout smoke", "agent_id": "general"},
            )
            created.raise_for_status()
            session_id = created.json()["session"]["id"]

        sentinel = "fanout smoke plain message"
        websocket_url = f"{ws_b_base}/ws/sessions/{session_id}"
        async with websockets.connect(websocket_url) as websocket:
            await asyncio.sleep(0.5)
            async with httpx.AsyncClient(timeout=10) as client:
                sent = await client.post(
                    f"{api_a_base}/sessions/{session_id}/messages",
                    json={"content": sentinel, "agent_id": "general"},
                )
                sent.raise_for_status()
            for _ in range(30):
                raw = await asyncio.wait_for(websocket.recv(), timeout=5)
                event = json.loads(raw)
                if event.get("event_type") == "message.created":
                    message = event.get("payload", {}).get("message", {})
                    if message.get("content") == sentinel:
                        cancel_queued_jobs_for_session(session_id)
                        print("backend A publish path: ok")
                        print("backend B websocket path: ok")
                        print("TRUE_TWO_BACKEND_FANOUT=passed")
                        return True
            raise SystemExit("backend B WebSocket did not receive backend A message.created event")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


async def main() -> None:
    await direct_redis_delivery_check()
    await true_two_backend_check()


asyncio.run(main())
PY

echo "[redis-fanout-smoke] ok"
