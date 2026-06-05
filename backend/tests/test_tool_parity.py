from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.core.events import EventType
from backend.app.db.models import Session
from backend.app.runtime.tool_executor import ToolExecutor
from backend.app.tools.base import ToolContext, ToolResult, content_sha256
from backend.app.tools.edit import EditFileInput, EditFileTool
from backend.app.tools.glob import GlobSearchInput, GlobSearchTool
from backend.app.tools.grep import GrepSearchInput, GrepSearchTool
from backend.app.tools.patch import PatchApplyInput, PatchApplyTool
from backend.app.tools.read import ReadFileInput, ReadFileTool
from backend.app.tools.todo import TodoItem, TodoWriteInput, TodoWriteTool
from backend.app.tools.write import WriteFileInput, WriteFileTool
from backend.tests.fakes import FakeAsyncSession


def _ctx(workspace_root: Path) -> ToolContext:
    return ToolContext(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_id="test",
        workspace_root=workspace_root,
    )


def _ensure_symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink privilege unavailable on this Windows session: {exc}")


def test_tool_result_failure_is_structured() -> None:
    result = ToolResult.failure(
        code="example_error",
        message="Example failed.",
        detail={"field": "value"},
        recoverable=False,
    )

    payload = result.model_dump(mode="json")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "example_error"
    assert payload["error"]["recoverable"] is False
    assert payload["artifacts"] == []


async def test_read_file_line_range_binary_and_symlink_safety(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (workspace / "blob.bin").write_bytes(b"abc\x00def")
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    _ensure_symlink_or_skip(workspace / "outside-link.txt", outside / "secret.txt")

    tool = ReadFileTool()
    context = _ctx(workspace)

    result = await tool.run(ReadFileInput(path="notes.txt", offset=2, limit=1, line_numbers=False), context)
    assert result.ok is True
    assert result.output["content"] == "beta"
    assert result.output["line_start"] == 2
    assert result.output["line_end"] == 2

    binary = await tool.run(ReadFileInput(path="blob.bin"), context)
    assert binary.ok is False
    assert binary.error is not None
    assert binary.error.code == "binary_file_refused"

    with pytest.raises(PermissionError):
        await tool.run(ReadFileInput(path="outside-link.txt"), context)


async def test_write_file_atomic_hash_backup_and_external_safety(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = _ctx(workspace)
    tool = WriteFileTool()

    created = await tool.run(
        WriteFileInput(path="nested/notes.txt", content="hello\n", create_dirs=True),
        context,
    )
    target = workspace / "nested" / "notes.txt"
    assert created.ok is True
    assert created.output["created"] is True
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert not list(target.parent.glob(".notes.txt.*.tmp"))

    current_hash = created.output["sha256"]
    overwritten = await tool.run(
        WriteFileInput(path="nested/notes.txt", content="hello again\n", expected_existing_hash=current_hash),
        context,
    )
    assert overwritten.ok is True
    assert overwritten.output["overwritten"] is True
    assert overwritten.output["backup_path"]
    assert Path(overwritten.output["backup_path"]).exists()

    stale = await tool.run(
        WriteFileInput(path="nested/notes.txt", content="bad\n", expected_existing_hash="0" * 64),
        context,
    )
    assert stale.ok is False
    assert stale.error is not None
    assert stale.error.code == "stale_file_hash"

    with pytest.raises(PermissionError):
        await tool.run(WriteFileInput(path="../outside.txt", content="nope\n"), context)


async def test_edit_file_exact_dry_run_multiple_match_and_hash_guard(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "notes.txt"
    path.write_text("one\ntwo\ntwo\n", encoding="utf-8")
    context = _ctx(workspace)
    tool = EditFileTool()

    ambiguous = await tool.run(EditFileInput(path="notes.txt", old="two", new="TWO"), context)
    assert ambiguous.ok is False
    assert ambiguous.error is not None
    assert ambiguous.error.code == "ambiguous_match"

    dry_run = await tool.run(
        EditFileInput(path="notes.txt", old="one", new="ONE", dry_run=True),
        context,
    )
    assert dry_run.ok is True
    assert "-one" in dry_run.output["diff"]
    assert path.read_text(encoding="utf-8").startswith("one")

    stale = await tool.run(
        EditFileInput(path="notes.txt", old="one", new="ONE", expected_existing_hash="0" * 64),
        context,
    )
    assert stale.ok is False
    assert stale.error is not None
    assert stale.error.code == "stale_file_hash"

    current_hash = content_sha256(path.read_text(encoding="utf-8"))
    edited = await tool.run(
        EditFileInput(path="notes.txt", old="one", new="ONE", expected_existing_hash=current_hash),
        context,
    )
    assert edited.ok is True
    assert path.read_text(encoding="utf-8").startswith("ONE")


async def test_patch_apply_dry_run_apply_and_traversal_block(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("old\n", encoding="utf-8")
    context = _ctx(workspace)
    tool = PatchApplyTool()

    add_patch = """*** Begin Patch
*** Add File: new.txt
+created
*** End Patch"""
    dry_run = await tool.run(PatchApplyInput(patch_text=add_patch, dry_run=True), context)
    assert dry_run.ok is True
    assert dry_run.output["dry_run"] is True
    assert not (workspace / "new.txt").exists()

    update_patch = """*** Begin Patch
*** Update File: notes.txt
@@
-old
+new
*** End Patch"""
    applied = await tool.run(PatchApplyInput(patch_text=update_patch), context)
    assert applied.ok is True
    assert applied.output["changed_files"][0]["type"] == "update"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "new\n"

    traversal_patch = """*** Begin Patch
*** Add File: ../evil.txt
+bad
*** End Patch"""
    with pytest.raises(PermissionError):
        await tool.run(PatchApplyInput(patch_text=traversal_patch), context)


async def test_grep_search_literal_regex_context_limits_and_secret_skip(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("before\nneedle one\nafter\nneedle two\n", encoding="utf-8")
    (workspace / "README.md").write_text("needle docs\n", encoding="utf-8")
    (workspace / ".env").write_text("API_TOKEN=needle-secret\n", encoding="utf-8")
    context = _ctx(workspace)
    tool = GrepSearchTool()

    result = await tool.run(
        GrepSearchInput(
            pattern="needle",
            literal=True,
            include=["*.py"],
            context_before=1,
            context_after=1,
            max_matches=1,
        ),
        context,
    )
    assert result.ok is True
    assert result.output["match_count"] == 1
    assert result.output["matches"][0]["before"] == ["before"]
    assert result.output["matches"][0]["after"] == ["after"]
    assert result.truncated is True

    regex = await tool.run(GrepSearchInput(pattern=r"needle\s+docs", include=["*.md"]), context)
    assert regex.output["match_count"] == 1

    all_files = await tool.run(GrepSearchInput(pattern="needle", literal=True, include=["*"]), context)
    assert all_files.output["skipped_protected_files"] == 1
    assert "needle-secret" not in str(all_files.output)


async def test_glob_search_hidden_exclude_limits_and_symlink_block(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "a.py").write_text("", encoding="utf-8")
    (workspace / "b.py").write_text("", encoding="utf-8")
    (workspace / ".hidden.py").write_text("", encoding="utf-8")
    (workspace / "skip.py").write_text("", encoding="utf-8")
    (outside / "external.py").write_text("", encoding="utf-8")
    _ensure_symlink_or_skip(workspace / "external-link.py", outside / "external.py")
    context = _ctx(workspace)
    tool = GlobSearchTool()

    visible = await tool.run(
        GlobSearchInput(pattern="*.py", exclude=["skip.py"], max_results=1),
        context,
    )
    relative_paths = {item["relative_path"] for item in visible.output["results"]}
    assert ".hidden.py" not in relative_paths
    assert "skip.py" not in relative_paths
    assert visible.output["blocked_symlinks"] == 1
    assert visible.truncated is True

    hidden = await tool.run(GlobSearchInput(pattern="*.py", include_hidden=True), context)
    assert ".hidden.py" in {item["relative_path"] for item in hidden.output["results"]}


async def test_todo_tool_persists_session_metadata_and_emits_event() -> None:
    session = Session(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        created_by_user_id=uuid4(),
        title="Test",
        agent_id="general",
        model_name="llama3.2:3b",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[session])
    result = await TodoWriteTool().run(
        TodoWriteInput(todos=[TodoItem(content="Inspect files", status="in_progress", priority="high")]),
        _ctx(Path("/tmp")),
    )

    await ToolExecutor()._apply_success_side_effects(
        db,
        tool_name="todo.write",
        session_id=session.id,
        result=result,
    )

    assert session.metadata_json["todos"][0]["content"] == "Inspect files"
    assert any(row.event_type == EventType.TODO_UPDATED for row in db.added if hasattr(row, "event_type"))
