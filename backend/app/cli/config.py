import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CliConfig:
    base_url: str = "http://localhost:8000"
    ws_url: str = "ws://localhost:8000"
    timeout_seconds: float = 30.0
    stream_reconnect_attempts: int = 5


def load_cli_config() -> CliConfig:
    return CliConfig(
        base_url=os.getenv("AP_CLI_BASE_URL", "http://localhost:8000").rstrip("/"),
        ws_url=os.getenv("AP_CLI_WS_URL", "ws://localhost:8000").rstrip("/"),
        timeout_seconds=float(os.getenv("AP_CLI_TIMEOUT_SECONDS", "30")),
        stream_reconnect_attempts=int(os.getenv("AP_CLI_STREAM_RECONNECT_ATTEMPTS", "5")),
    )
