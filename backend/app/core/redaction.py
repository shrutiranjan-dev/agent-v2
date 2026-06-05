import os
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|credential|private[_-]?key|access[_-]?key|auth)",
    re.IGNORECASE,
)
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
ASSIGNMENT_RE = re.compile(
    r"(?im)\b([A-Z0-9_.-]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|AUTH)[A-Z0-9_.-]*)\s*=\s*([^\s\r\n]+)"
)
JSON_ASSIGNMENT_RE = re.compile(
    r'(?i)("?(?:api[_-]?key|token|secret|password|passwd|credential|private[_-]?key|access[_-]?key|auth)"?\s*:\s*")([^"]+)(")'
)
LONG_TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{48,})\b")


def is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_RE.search(key))


def redact_text(value: str) -> str:
    if not value:
        return value
    redacted = PRIVATE_KEY_RE.sub(REDACTED, value)
    redacted = BEARER_RE.sub(f"Bearer {REDACTED}", redacted)
    redacted = ASSIGNMENT_RE.sub(r"\1=" + REDACTED, redacted)
    redacted = JSON_ASSIGNMENT_RE.sub(r"\1" + REDACTED + r"\3", redacted)
    redacted = LONG_TOKEN_RE.sub(REDACTED, redacted)
    return redacted


def redact_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return [redact_data(item) for item in value]
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_string = str(key)
            output[key_string] = REDACTED if is_sensitive_key(key_string) else redact_data(item)
        return output
    return value


def scrub_process_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = env or os.environ
    return {key: value for key, value in source.items() if not is_sensitive_key(key)}
