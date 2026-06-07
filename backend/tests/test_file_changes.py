from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes_file_changes import router as file_changes_router
from backend.app.db.models import FileChange
from backend.app.db.postgres import get_session
from backend.app.file_changes.file_change_service import (
    FileChangeAlreadyReverted,
    FileChangeContext,
    FileChangeError,
    FileChangeNotRevertible,
    build_captures_for_tool,
    capture_for_tool_call,
    capture_from_tool_call,
    get_file_change,
    list_file_changes,
    revert_file_change,
    serialize_file_change,
)
from backend.app.main import create_app
from backend.app.tools.base import ToolContext
from backend.app.tools.edit import EditFileInput, EditFileTool
from backend.app.tools.patch import PatchApplyInput, PatchApplyTool
from backend.app.tools.write import WriteFileInput, WriteFileTool
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import make_session

SNAPSHOT = {
    "enabled": True,
    "capture_content": True,
    "capture_diff": True,
    "max_content_bytes": 64 * 1024,
    "max_diff_bytes": 32 * 1024,
    "secret_filename_globs": [
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "id_rsa",
        "id_rsa.*",
        "id_ed25519",
        "id_ed25519.*",
        "credentials",
        "credentials.*",
        "*credentials*",
        "service-account*.json",
    ],
}


def _ctx(workspace_root: Path) -> ToolContext:
    return ToolContext(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_id="test",
        workspace_root=workspace_root,
    )


def _file_change_ctx(tmp_path: Path, *, session_id=None) -> FileChangeContext:
    return FileChangeContext(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=session_id or uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=uuid4(),
        workspace_root=tmp_path,
    )


async def test_write_file_capture_creates_file_change(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("old content\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path="notes.txt", content="hello world\n"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": "notes.txt", "content": "hello world\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.tool_name == "write.file"
    assert row.operation == "write"
    assert row.relative_path == "notes.txt"
    assert row.after_sha256 is not None
    assert row.before_sha256 is not None
    assert row.revertible is True
    assert row.revert_status == "not_reverted"
    assert row.after_content == "hello world\n"
    assert row.diff and "hello world" in row.diff
    assert db.added[0].__class__.__name__ == "FileChange"


async def test_edit_file_capture_records_before_and_after(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = EditFileTool()
    result = await tool.run(
        EditFileInput(path="notes.txt", old="beta", new="BETA"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="edit.file",
        input_json={"path": "notes.txt", "old": "beta", "new": "BETA"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.tool_name == "edit.file"
    assert row.operation == "edit"
    assert row.before_sha256 is not None
    assert row.after_sha256 is not None
    assert row.replacement_count == 1
    assert row.diff and "-beta" in row.diff and "+BETA" in row.diff


async def test_edit_file_dry_run_is_not_captured(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("alpha\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = EditFileTool()
    result = await tool.run(
        EditFileInput(path="notes.txt", old="alpha", new="ALPHA", dry_run=True),
        ctx,
    )
    assert result.ok

    captures = build_captures_for_tool(
        tool_name="edit.file",
        input_json={"path": "notes.txt", "old": "alpha", "new": "ALPHA"},
        result_output=result.output,
        result_metadata=result.metadata,
        workspace_root=workspace,
    )
    assert captures == []


async def test_patch_apply_capture_creates_one_change_per_file(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("one\n", encoding="utf-8")
    (workspace / "b.txt").write_text("two\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = PatchApplyTool()
    patch = (
        "*** Begin Patch\n"
        "*** Update File: a.txt\n"
        "@@\n"
        "-one\n"
        "+ONE\n"
        "*** Update File: b.txt\n"
        "@@\n"
        "-two\n"
        "+TWO\n"
        "*** End Patch"
    )
    result = await tool.run(PatchApplyInput(patch_text=patch), ctx)
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="patch.apply",
        input_json={"patch_text": patch},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    paths = sorted(row.relative_path for row in rows)
    assert paths == ["a.txt", "b.txt"]
    assert {row.operation for row in rows} == {"update"}


async def test_secret_file_redaction_and_non_revertible(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / ".env"
    target.write_text("API_KEY=secret\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path=".env", content="NEW=value\n"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": ".env", "content": "NEW=value\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.redacted is True
    assert row.redaction_reason == "secret_filename_match"
    assert row.revertible is False
    assert row.before_content is None
    assert row.after_content is None
    assert row.diff is None


async def test_truncation_for_large_content_and_diff(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "big.txt").write_text("x" * 1024, encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    big = "y" * (SNAPSHOT["max_content_bytes"] + 100)
    result = await tool.run(
        WriteFileInput(path="big.txt", content=big + "\n"),
        ctx,
    )
    assert result.ok

    small_snapshot = {**SNAPSHOT, "max_content_bytes": 256, "max_diff_bytes": 256}
    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": "big.txt", "content": big + "\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=small_snapshot,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.after_content is not None
    assert row.after_content_truncated is True
    assert row.after_content.endswith("...truncated...")


async def test_failed_tool_call_does_not_create_change(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("alpha\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = EditFileTool()
    result = await tool.run(
        EditFileInput(path="notes.txt", old="missing-text", new="x"),
        ctx,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "old_text_not_found"

    captures = build_captures_for_tool(
        tool_name="edit.file",
        input_json={"path": "notes.txt", "old": "missing-text", "new": "x"},
        result_output=result.output,
        result_metadata=result.metadata,
        workspace_root=workspace,
    )
    assert captures == []


async def test_revert_writes_back_before_content(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("original\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path="notes.txt", content="modified\n"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": "notes.txt", "content": "modified\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    assert len(rows) == 1
    change_id = rows[0].id

    updated = await revert_file_change(
        db,
        file_change_id=change_id,
        workspace_root=workspace,
        actor_user_id=uuid4(),
    )
    assert updated.revert_status == "reverted"
    assert target.read_text(encoding="utf-8") == "original\n"


async def test_revert_refuses_if_hash_mismatch(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("original\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path="notes.txt", content="modified\n"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": "notes.txt", "content": "modified\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    change_id = rows[0].id

    target.write_text("someone else wrote this\n", encoding="utf-8")
    with pytest.raises(FileChangeError):
        await revert_file_change(
            db,
            file_change_id=change_id,
            workspace_root=workspace,
            actor_user_id=None,
        )


async def test_revert_refuses_for_secret_file(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path=".env", content="NEW=value\n"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": ".env", "content": "NEW=value\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    change_id = rows[0].id
    with pytest.raises(FileChangeNotRevertible):
        await revert_file_change(
            db,
            file_change_id=change_id,
            workspace_root=workspace,
            actor_user_id=None,
        )


async def test_revert_refuses_when_already_reverted(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("original\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path="notes.txt", content="modified\n"),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": "notes.txt", "content": "modified\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    change_id = rows[0].id
    await revert_file_change(
        db,
        file_change_id=change_id,
        workspace_root=workspace,
        actor_user_id=None,
    )
    with pytest.raises(FileChangeAlreadyReverted):
        await revert_file_change(
            db,
            file_change_id=change_id,
            workspace_root=workspace,
            actor_user_id=None,
        )


async def test_revert_can_delete_added_file(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path="new.txt", content="hello\n", create_dirs=True),
        ctx,
    )
    assert result.ok

    db = FakeAsyncSession()
    rows = await capture_for_tool_call(
        db,
        ctx=_file_change_ctx(workspace),
        tool_name="write.file",
        input_json={"path": "new.txt", "content": "hello\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=SNAPSHOT,
    )
    change_id = rows[0].id
    target = workspace / "new.txt"
    assert target.exists()
    await revert_file_change(
        db,
        file_change_id=change_id,
        workspace_root=workspace,
        actor_user_id=None,
    )
    assert not target.exists()


async def test_list_and_serialize_file_changes() -> None:
    db = FakeAsyncSession()
    session = make_session()
    row = FileChange(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path="src/main.py",
        resolved_path="/workspace/src/main.py",
        before_sha256=None,
        after_sha256="a" * 64,
        before_size_bytes=None,
        after_size_bytes=128,
        before_content=None,
        after_content="print('hello')\n",
        diff="+print('hello')\n",
        additions=1,
        deletions=0,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    db.add(row)

    listed = await list_file_changes(db, session_id=session.id)
    assert len(listed) == 1
    assert listed[0].id == row.id

    fetched = await get_file_change(db, row.id)
    assert fetched is not None
    assert fetched.id == row.id

    payload = serialize_file_change(fetched, include_content=False)
    assert "resolved_path" not in payload
    assert payload["relative_path"] == "src/main.py"
    assert payload["diff"] is None
    assert payload["before_content"] is None
    assert payload["after_content"] is None

    full_payload = serialize_file_change(fetched, include_content=True)
    assert full_payload["diff"] == "+print('hello')\n"
    assert full_payload["after_content"] == "print('hello')\n"


async def test_list_filters_by_path_and_revert_status() -> None:
    db = FakeAsyncSession()
    session = make_session()
    rows = [
        FileChange(
            id=uuid4(),
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=uuid4(),
            tool_call_id=None,
            tool_name="write.file",
            operation="write",
            relative_path="a.py",
            resolved_path="/workspace/a.py",
            before_sha256=None,
            after_sha256="a" * 64,
            before_size_bytes=None,
            after_size_bytes=10,
            before_content=None,
            after_content="hello\n",
            diff="+hello\n",
            additions=1,
            deletions=0,
            replacement_count=1,
            redacted=False,
            revertible=True,
            revert_status="not_reverted",
            metadata_json={},
        ),
        FileChange(
            id=uuid4(),
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=uuid4(),
            tool_call_id=None,
            tool_name="edit.file",
            operation="edit",
            relative_path="b.py",
            resolved_path="/workspace/b.py",
            before_sha256="b" * 64,
            after_sha256="c" * 64,
            before_size_bytes=5,
            after_size_bytes=10,
            before_content="old\n",
            after_content="new\n",
            diff="-old\n+new\n",
            additions=1,
            deletions=1,
            replacement_count=1,
            redacted=False,
            revertible=True,
            revert_status="reverted",
            metadata_json={},
        ),
    ]
    for row in rows:
        db.add(row)

    a_rows = await list_file_changes(db, session_id=session.id, relative_path="a.py")
    assert [row.id for row in a_rows] == [rows[0].id]

    reverted = await list_file_changes(db, session_id=session.id, revert_status="reverted")
    assert [row.id for row in reverted] == [rows[1].id]


def test_routes_register() -> None:
    assert file_changes_router.prefix == "/file-changes"


def test_route_lists_metadata_only_by_default() -> None:
    session = make_session()
    row = FileChange(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path="src/main.py",
        resolved_path="/workspace/src/main.py",
        before_sha256=None,
        after_sha256="a" * 64,
        before_size_bytes=None,
        after_size_bytes=10,
        before_content=None,
        after_content="print('hi')\n",
        diff="+print('hi')\n",
        additions=1,
        deletions=0,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[session, row])
    app = create_app()

    async def override_get_session():
        yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        response = client.get(f"/file-changes?session_id={session.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    payload = body["file_changes"][0]
    assert "resolved_path" not in payload
    assert payload["relative_path"] == "src/main.py"
    assert payload["diff"] is None
    assert payload["before_content"] is None
    assert payload["after_content"] is None


def test_route_detail_supports_include_content() -> None:
    session = make_session()
    row = FileChange(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path="src/main.py",
        resolved_path="/workspace/src/main.py",
        before_sha256=None,
        after_sha256="a" * 64,
        before_size_bytes=None,
        after_size_bytes=10,
        before_content=None,
        after_content="print('hi')\n",
        diff="+print('hi')\n",
        additions=1,
        deletions=0,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[session, row])
    app = create_app()

    async def override_get_session():
        yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        meta_only = client.get(f"/file-changes/{row.id}?include_content=false")
        with_content = client.get(f"/file-changes/{row.id}?include_content=true")
        missing = client.get(f"/file-changes/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert meta_only.status_code == 200
    assert meta_only.json()["file_change"]["diff"] is None
    assert with_content.status_code == 200
    assert with_content.json()["file_change"]["diff"] == "+print('hi')\n"
    assert missing.status_code == 404


def test_revert_route_happy_path(tmp_path) -> None:
    from backend.app.tools.base import content_sha256, file_sha256

    target = tmp_path / "notes.txt"
    target.write_bytes(b"modified\n")
    after_sha = content_sha256("modified\n")
    row = FileChange(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path="notes.txt",
        resolved_path=str(target),
        before_sha256=content_sha256("original\n"),
        after_sha256=after_sha,
        before_size_bytes=9,
        after_size_bytes=9,
        before_content="original\n",
        after_content="modified\n",
        diff="-original\n+modified\n",
        additions=1,
        deletions=1,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    actual_file_hash = file_sha256(target)
    assert actual_file_hash == after_sha, f"Test setup hash mismatch: {actual_file_hash} != {after_sha}"

    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_requires_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = tmp_path
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(f"/file-changes/{row.id}/revert", json={"force": False})
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().file_changes.revert_requires_approval = original_requires_approval

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_change"]["revert_status"] == "reverted"
    assert target.read_bytes() == b"original\n"


def test_revert_route_refuses_redacted(tmp_path) -> None:
    target = tmp_path / ".env"
    target.write_text("API_KEY=secret\n", encoding="utf-8")
    row = FileChange(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path=".env",
        resolved_path=str(target),
        before_sha256=None,
        after_sha256="a" * 64,
        before_size_bytes=None,
        after_size_bytes=10,
        before_content=None,
        after_content="NEW=value\n",
        diff="+NEW=value\n",
        additions=1,
        deletions=0,
        replacement_count=1,
        redacted=True,
        redaction_reason="secret_filename_match",
        revertible=False,
        revert_status="not_reverted",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_requires_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = tmp_path
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(f"/file-changes/{row.id}/revert", json={"force": True})
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().file_changes.revert_requires_approval = original_requires_approval

    assert response.status_code == 403


async def test_capture_disabled_short_circuits(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("old\n", encoding="utf-8")
    ctx = _ctx(workspace)
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path="notes.txt", content="new\n"),
        ctx,
    )
    assert result.ok

    from backend.app.file_changes import file_change_service

    original = file_change_service.file_change_settings_snapshot
    file_change_service.file_change_settings_snapshot = lambda: {**SNAPSHOT, "enabled": False}
    try:
        db = FakeAsyncSession()
        rows = await capture_from_tool_call(
            db,
            ctx=_file_change_ctx(workspace),
            tool_name="write.file",
            input_json={"path": "notes.txt", "content": "new\n"},
            result_output=result.output,
            result_metadata=result.metadata,
        )
    finally:
        file_change_service.file_change_settings_snapshot = original

    assert rows == []


def test_serialize_does_not_leak_resolved_path() -> None:
    row = FileChange(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_run_id=None,
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path="src/secret/notes.txt",
        resolved_path="/home/user/workspace/src/secret/notes.txt",
        before_sha256=None,
        after_sha256="a" * 64,
        before_size_bytes=None,
        after_size_bytes=10,
        before_content=None,
        after_content="hi\n",
        diff="+hi\n",
        additions=1,
        deletions=0,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    payload = serialize_file_change(row, include_content=True)
    assert "resolved_path" not in payload
    assert "/home/user" not in json.dumps(payload)
