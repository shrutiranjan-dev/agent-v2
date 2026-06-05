import json

import pytest

from backend.app.runtime.agent_runner import _extract_json, _fallback_final_content


def test_extract_json_accepts_plain_object() -> None:
    assert _extract_json('{"type":"final","content":"ok"}') == {"type": "final", "content": "ok"}


def test_extract_json_accepts_fenced_json() -> None:
    assert _extract_json('```json\n{"type":"final","content":"ok"}\n```')["content"] == "ok"


def test_extract_json_rejects_invalid_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json")


def test_fallback_final_content_preserves_plain_text() -> None:
    assert _fallback_final_content("  normal model answer  ") == "normal model answer"
    assert _fallback_final_content("", "fallback") == "fallback"
