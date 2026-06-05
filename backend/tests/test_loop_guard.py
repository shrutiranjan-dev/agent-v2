from uuid import uuid4

import pytest

from backend.app.runtime.loop_guard import input_hash, loop_guard


class FakeDB:
    async def scalar(self, _statement):
        return 2

    def add(self, _row):
        return None

    async def flush(self):
        return None


async def test_loop_guard_blocks_third_identical_call(monkeypatch) -> None:
    async def publish(*args, **kwargs):
        return None

    monkeypatch.setattr("backend.app.runtime.loop_guard.event_bus.publish", publish)
    with pytest.raises(RuntimeError):
        await loop_guard.assert_not_repeated(
            FakeDB(),
            organization_id=uuid4(),
            project_id=uuid4(),
            workspace_id=uuid4(),
            session_id=uuid4(),
            agent_id="build",
            tool_name="read.file",
            input_json={"path": "README.md"},
        )


def test_input_hash_is_stable_for_key_order() -> None:
    assert input_hash({"a": 1, "b": 2}) == input_hash({"b": 2, "a": 1})

