from datetime import UTC, datetime
from uuid import uuid4

from backend.app.db.models import Session
from backend.app.runtime.session_service import serialize_session


def test_serialize_session() -> None:
    now = datetime.now(UTC)
    session = Session(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        created_by_user_id=uuid4(),
        title="Example",
        agent_id="build",
        model_provider="ollama",
        model_name="qwen2.5-coder:7b",
        status="idle",
        metadata_json={"k": "v"},
        created_at=now,
        updated_at=now,
    )
    data = serialize_session(session)
    assert data["title"] == "Example"
    assert data["metadata"] == {"k": "v"}

