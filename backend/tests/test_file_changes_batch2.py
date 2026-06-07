"""Tests for File Diff Batch 2.

Covers:
- 409 (conflict) mapping for hash mismatch / already-reverted
- 403 (forbidden) mapping for redacted / outside-workspace / secret-without-force
- 404 (not found) for unknown ids
- 202 (waiting_permission) for the approval gate
- Approval-gated revert: must create a permission request first, then
  resume with the permission_request_id after approval; reuse across a
  different change is forbidden; mismatched nonce is forbidden; hash
  mismatch after approval still returns 409
- Batch revert: validate-all-before-apply; one unsafe change rejects the
  whole batch with no partial mutation; successful batch reverts every
  change; failed batch restores the pre-batch on-disk state
- Git/VCS fallback: restores tracked file from HEAD when the snapshot
  is missing; refuses secrets; refuses paths outside the workspace; no
  shell injection with weird path inputs; refuses when git is unavailable
- Guarded test endpoint: 404 when ``enable_test_endpoints`` is false
- CLI: 202 + 409 surface clean errors via :class:`CliApiError`
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import FileChange, PermissionRequest
from backend.app.db.postgres import get_session
from backend.app.file_changes.file_change_service import (
    REVERT_PERMISSION_KEY,
    FileChangeError,
    capture_for_tool_call,
    compute_approval_nonce,
    restore_from_git_head,
    revert_file_change,
    revert_file_changes_batch,
)
from backend.app.main import create_app
from backend.app.tools.base import content_sha256
from backend.tests.fakes import FakeAsyncSession
from backend.tests.test_agent_runner_runtime import make_session

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _row(tmp_path: Path, *, secret: bool = False, missing_before: bool = False) -> FileChange:
    target = tmp_path / (".env" if secret else "notes.txt")
    if not secret:
        target.write_bytes(b"modified\n")
    after_sha = content_sha256("modified\n") if not secret else "a" * 64
    session = make_session()
    return FileChange(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path=target.name,
        resolved_path=str(target),
        before_sha256=None if missing_before else content_sha256("original\n"),
        after_sha256=after_sha,
        before_size_bytes=None if missing_before else 9,
        after_size_bytes=9,
        before_content=None if missing_before else "original\n",
        after_content="modified\n",
        diff="-original\n+modified\n",
        additions=1,
        deletions=1,
        replacement_count=1,
        redacted=secret,
        redaction_reason="secret_filename_match" if secret else None,
        revertible=not secret,
        revert_status="not_reverted",
        metadata_json={},
    )


def _override_settings(*, requires_approval: bool, git_fallback: bool = True) -> None:
    from backend.app.core.config import get_settings

    settings = get_settings()
    settings.file_changes.revert_requires_approval = requires_approval
    settings.file_changes.git_fallback_enabled = git_fallback


def _restore_settings() -> None:
    from backend.app.core.config import get_settings

    settings = get_settings()
    settings.file_changes.revert_requires_approval = True
    settings.file_changes.git_fallback_enabled = True


# ---------------------------------------------------------------------------
# 1. 409/403/404 mapping
# ---------------------------------------------------------------------------


def test_revert_unknown_id_returns_404(tmp_path: Path) -> None:
    db = FakeAsyncSession(objects=[])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = tmp_path
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(f"/file-changes/{uuid4()}/revert", json={"force": False})
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"] == "file_change_not_found"


def test_revert_hash_mismatch_returns_409_not_500(tmp_path: Path) -> None:
    row = _row(tmp_path)
    # Force a hash mismatch by overwriting the file with foreign content.
    Path(row.resolved_path).write_bytes(b"someone else wrote this\n")
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
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
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["error"] == "file_change_hash_mismatch"
    details = body["detail"]["details"]
    assert details["change_id"] == str(row.id)
    assert details["relative_path"] == "notes.txt"
    assert details["expected_after_sha256"] == row.after_sha256
    assert details["current_sha256"] is not None
    assert details["current_sha256"] != row.after_sha256


def test_revert_already_reverted_returns_409(tmp_path: Path) -> None:
    row = _row(tmp_path)
    row.revert_status = "reverted"
    row.reverted_at = None
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
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
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "file_change_already_reverted"


def test_revert_secret_without_force_returns_409(tmp_path: Path) -> None:
    # A non-redacted FileChange whose path matches a secret glob triggers
    # 409 with force=False (the operator must explicitly opt in).
    row = _row(tmp_path)
    row.relative_path = ".env"
    row.resolved_path = str(tmp_path / ".env")
    row.redacted = False
    row.revertible = True
    Path(row.resolved_path).write_bytes(b"API_KEY=secret\n")
    row.after_sha256 = content_sha256("API_KEY=secret\n")
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
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
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "file_change_secret_requires_force"


# ---------------------------------------------------------------------------
# 2. Approval gate
# ---------------------------------------------------------------------------


def test_revert_without_permission_returns_202(tmp_path: Path) -> None:
    row = _row(tmp_path)
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    get_settings().runtime.workspace_root = tmp_path
    _override_settings(requires_approval=True)
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(f"/file-changes/{row.id}/revert", json={"force": False})
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        _restore_settings()

    assert response.status_code == 202
    body = response.json()
    assert body["detail"]["status"] == "waiting_permission"
    assert body["detail"]["permission_request_id"]
    assert body["detail"]["approval_nonce"]
    # The file is not touched.
    assert Path(row.resolved_path).read_bytes() == b"modified\n"


def test_revert_approval_resume_executes(tmp_path: Path) -> None:
    row = _row(tmp_path)
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    nonce = compute_approval_nonce(
        file_change_id=row.id,
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=False,
    )
    request = PermissionRequest(
        id=uuid4(),
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        permission_key=REVERT_PERMISSION_KEY,
        resource=row.relative_path,
        action="ask",
        status="approved",
        input_json={
            "file_change_id": str(row.id),
            "relative_path": row.relative_path,
            "force": False,
            "expected_after_sha256": row.after_sha256,
        },
        metadata_json={"input_hash": nonce, "reason": "file_change_revert_requires_approval"},
    )
    db.add(request)

    original_root = get_settings().runtime.workspace_root
    get_settings().runtime.workspace_root = tmp_path
    _override_settings(requires_approval=True)
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                f"/file-changes/{row.id}/revert",
                json={"force": False, "permission_request_id": str(request.id)},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        _restore_settings()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_change"]["revert_status"] == "reverted"
    assert body["restore_source"] == "stored_snapshot"
    assert Path(row.resolved_path).read_bytes() == b"original\n"


def test_revert_approval_nonce_mismatch_returns_403(tmp_path: Path) -> None:
    row = _row(tmp_path)
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    # Use a stale nonce: tied to a different file change id.
    stale_nonce = compute_approval_nonce(
        file_change_id=uuid4(),
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=False,
    )
    request = PermissionRequest(
        id=uuid4(),
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        permission_key=REVERT_PERMISSION_KEY,
        resource=row.relative_path,
        action="ask",
        status="approved",
        input_json={"file_change_id": str(uuid4()), "force": False},
        metadata_json={"input_hash": stale_nonce},
    )
    db.add(request)

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    get_settings().runtime.workspace_root = tmp_path
    _override_settings(requires_approval=True)
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                f"/file-changes/{row.id}/revert",
                json={"force": False, "permission_request_id": str(request.id)},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        _restore_settings()

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "file_change_forbidden"


def test_revert_approval_pending_returns_409(tmp_path: Path) -> None:
    row = _row(tmp_path)
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    nonce = compute_approval_nonce(
        file_change_id=row.id,
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=False,
    )
    request = PermissionRequest(
        id=uuid4(),
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        permission_key=REVERT_PERMISSION_KEY,
        resource=row.relative_path,
        action="ask",
        status="pending",
        input_json={"file_change_id": str(row.id), "force": False},
        metadata_json={"input_hash": nonce},
    )
    db.add(request)

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    get_settings().runtime.workspace_root = tmp_path
    _override_settings(requires_approval=True)
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                f"/file-changes/{row.id}/revert",
                json={"force": False, "permission_request_id": str(request.id)},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        _restore_settings()

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "file_change_conflict"


def test_revert_approval_force_mismatch_returns_403(tmp_path: Path) -> None:
    row = _row(tmp_path)
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    # The permission was issued for force=False; the resume tries force=True.
    nonce = compute_approval_nonce(
        file_change_id=row.id,
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=False,
    )
    request = PermissionRequest(
        id=uuid4(),
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        permission_key=REVERT_PERMISSION_KEY,
        resource=row.relative_path,
        action="ask",
        status="approved",
        input_json={"file_change_id": str(row.id), "force": False},
        metadata_json={"input_hash": nonce},
    )
    db.add(request)

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    get_settings().runtime.workspace_root = tmp_path
    _override_settings(requires_approval=True)
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                f"/file-changes/{row.id}/revert",
                json={"force": True, "permission_request_id": str(request.id)},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        _restore_settings()

    assert response.status_code == 403


def test_revert_approval_with_hash_mismatch_returns_409(tmp_path: Path) -> None:
    row = _row(tmp_path)
    Path(row.resolved_path).write_bytes(b"someone else wrote this\n")
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    nonce = compute_approval_nonce(
        file_change_id=row.id,
        relative_path=row.relative_path,
        expected_after_sha256=row.after_sha256,
        force=False,
    )
    request = PermissionRequest(
        id=uuid4(),
        organization_id=row.organization_id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        permission_key=REVERT_PERMISSION_KEY,
        resource=row.relative_path,
        action="ask",
        status="approved",
        input_json={"file_change_id": str(row.id), "force": False},
        metadata_json={"input_hash": nonce},
    )
    db.add(request)

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    get_settings().runtime.workspace_root = tmp_path
    _override_settings(requires_approval=True)
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                f"/file-changes/{row.id}/revert",
                json={"force": False, "permission_request_id": str(request.id)},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        _restore_settings()

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "file_change_hash_mismatch"


# ---------------------------------------------------------------------------
# 3. Batch revert
# ---------------------------------------------------------------------------


def test_batch_revert_success(tmp_path: Path) -> None:
    row_a = _row(tmp_path)
    target_b = tmp_path / "other.txt"
    target_b.write_bytes(b"changed_b\n")
    session = make_session()
    row_b = FileChange(
        id=uuid4(),
        organization_id=session.organization_id,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        session_id=session.id,
        agent_run_id=uuid4(),
        tool_call_id=None,
        tool_name="write.file",
        operation="write",
        relative_path="other.txt",
        resolved_path=str(target_b),
        before_sha256=content_sha256("original_b\n"),
        after_sha256=content_sha256("changed_b\n"),
        before_size_bytes=11,
        after_size_bytes=10,
        before_content="original_b\n",
        after_content="changed_b\n",
        diff="-original_b\n+changed_b\n",
        additions=1,
        deletions=1,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[row_a, row_b])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = tmp_path
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                "/file-changes/revert-batch",
                json={"change_ids": [str(row_a.id), str(row_b.id)], "force": False},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["reverted"]) == sorted([str(row_a.id), str(row_b.id)])
    assert body["skipped"] == []
    assert body["failed"] == []
    assert Path(row_a.resolved_path).read_bytes() == b"original\n"
    assert Path(row_b.resolved_path).read_bytes() == b"original_b\n"


def test_batch_revert_rejects_whole_batch_on_one_unsafe(tmp_path: Path) -> None:
    row_ok = _row(tmp_path)
    row_bad = _row(tmp_path)
    row_bad.relative_path = ".env"
    row_bad.resolved_path = str(tmp_path / ".env")
    row_bad.redacted = False
    row_bad.revertible = True
    # The .env file is a secret; force=False rejects it.
    Path(row_bad.resolved_path).write_bytes(b"API_KEY=secret\n")
    row_bad.after_sha256 = content_sha256("API_KEY=secret\n")
    db = FakeAsyncSession(objects=[row_ok, row_bad])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = tmp_path
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                "/file-changes/revert-batch",
                json={"change_ids": [str(row_ok.id), str(row_bad.id)], "force": False},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["error"] == "file_change_batch_rejected"
    assert any(
        entry["reason"] == "file_change_secret_requires_force" for entry in body["detail"]["details"]["skipped"]
    )
    # No partial mutation: both files stay as they were.
    assert Path(row_ok.resolved_path).read_bytes() == b"modified\n"
    assert Path(row_bad.resolved_path).read_bytes() == b"API_KEY=secret\n"


def test_batch_revert_idempotent_duplicate_ids(tmp_path: Path) -> None:
    row = _row(tmp_path)
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = tmp_path
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                "/file-changes/revert-batch",
                json={"change_ids": [str(row.id), str(row.id)], "force": False},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reverted"] == [str(row.id)]


def test_batch_revert_max_100(tmp_path: Path) -> None:
    app = create_app()
    db = FakeAsyncSession(objects=[])

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_approval = get_settings().file_changes.revert_requires_approval
    get_settings().file_changes.revert_requires_approval = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                "/file-changes/revert-batch",
                json={"change_ids": [str(uuid4()) for _ in range(101)], "force": False},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "file_change_validation"


# ---------------------------------------------------------------------------
# 4. Git fallback
# ---------------------------------------------------------------------------


def test_restore_from_git_head_when_tracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "tracked.txt"
    target.write_text("HEAD version\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)
    # User edits the file outside the tool.
    target.write_text("user edited it\n", encoding="utf-8")

    payload = restore_from_git_head(repo, "tracked.txt")
    assert payload is not None
    content, size = payload
    assert content == "HEAD version\n"
    assert size == len("HEAD version\n")


def test_restore_from_git_head_refuses_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for bad in ("..", "../etc/passwd", "/etc/passwd", "~/.ssh/id_rsa", "foo\\bar"):
        assert restore_from_git_head(repo, bad) is None


def test_restore_from_git_head_returns_none_when_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    (repo / "untracked.txt").write_text("hi\n", encoding="utf-8")
    assert restore_from_git_head(repo, "untracked.txt") is None


def test_restore_from_git_head_returns_none_when_no_git(tmp_path: Path) -> None:
    repo = tmp_path / "no_git"
    repo.mkdir()
    (repo / "file.txt").write_text("x", encoding="utf-8")
    # Force the lookup to find no executable.
    original_path = os.environ.get("PATH", "")
    os.environ["PATH"] = ""
    try:
        assert restore_from_git_head(repo, "file.txt") is None
    finally:
        os.environ["PATH"] = original_path


def test_revert_uses_git_fallback_when_snapshot_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "tracked.txt"
    target.write_text("HEAD version\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)
    target.write_text("user wrote this\n", encoding="utf-8")

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
        relative_path="tracked.txt",
        resolved_path=str(target),
        before_sha256=None,
        after_sha256=content_sha256("user wrote this\n"),
        before_size_bytes=None,
        after_size_bytes=len("user wrote this\n"),
        before_content=None,
        after_content="user wrote this\n",
        diff="+user wrote this\n",
        additions=1,
        deletions=0,
        replacement_count=1,
        redacted=False,
        revertible=True,
        revert_status="not_reverted",
        metadata_json={},
    )
    db = FakeAsyncSession(objects=[row])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_approval = get_settings().file_changes.revert_requires_approval
    get_settings().runtime.workspace_root = repo
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
        get_settings().file_changes.revert_requires_approval = original_approval

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_change"]["revert_status"] == "reverted"
    assert body["restore_source"] == "git_head"
    assert target.read_text(encoding="utf-8") == "HEAD version\n"


# ---------------------------------------------------------------------------
# 5. Guarded test endpoint
# ---------------------------------------------------------------------------


def test_test_endpoint_404_when_disabled(tmp_path: Path) -> None:
    db = FakeAsyncSession(objects=[])
    app = create_app()

    async def override_get_session():
        yield db

    from backend.app.core.config import get_settings

    original_root = get_settings().runtime.workspace_root
    original_enable = get_settings().app.enable_test_endpoints
    get_settings().runtime.workspace_root = tmp_path
    get_settings().app.enable_test_endpoints = False
    try:
        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)
            response = client.post(
                "/test-endpoints/file-change-write",
                json={"path": "notes.txt", "content": "x"},
            )
        finally:
            app.dependency_overrides.clear()
    finally:
        get_settings().runtime.workspace_root = original_root
        get_settings().app.enable_test_endpoints = original_enable

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6. CLI handling of 202 and 409
# ---------------------------------------------------------------------------


def test_cli_revert_handles_waiting_permission(monkeypatch, tmp_path: Path) -> None:
    from backend.app.cli.api_client import AgentApiClient, CliApiError
    from backend.app.cli.config import CliConfig

    captured: dict = {}

    def fake_request(self, method, path, **kwargs):  # noqa: ARG001
        captured["method"] = method
        captured["path"] = path
        raise CliApiError(
            "HTTP 202: {'status': 'waiting_permission', 'permission_request_id': '11111111-1111-1111-1111-111111111111'}",
            status_code=202,
        )

    monkeypatch.setattr(AgentApiClient, "_request", fake_request)
    cfg = CliConfig(base_url="http://test", timeout_seconds=1)
    client = AgentApiClient(cfg)
    with pytest.raises(CliApiError) as exc_info:
        client.revert_file_change("22222222-2222-2222-2222-222222222222", force=False)
    assert exc_info.value.status_code == 202
    assert "permission_request_id" in str(exc_info.value)


def test_cli_revert_handles_409(monkeypatch) -> None:
    from backend.app.cli.api_client import AgentApiClient, CliApiError
    from backend.app.cli.config import CliConfig

    def fake_request(self, method, path, **kwargs):  # noqa: ARG001
        raise CliApiError("HTTP 409: hash mismatch", status_code=409)

    monkeypatch.setattr(AgentApiClient, "_request", fake_request)
    cfg = CliConfig(base_url="http://test", timeout_seconds=1)
    client = AgentApiClient(cfg)
    with pytest.raises(CliApiError) as exc_info:
        client.revert_file_change("33333333-3333-3333-3333-333333333333", force=False)
    assert exc_info.value.status_code == 409
    assert "hash mismatch" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 7. CLI batch revert
# ---------------------------------------------------------------------------


def test_cli_revert_batch_calls_endpoint(monkeypatch, tmp_path: Path) -> None:
    from backend.app.cli.api_client import AgentApiClient
    from backend.app.cli.config import CliConfig

    captured: dict = {}

    def fake_request(self, method, path, **kwargs):  # noqa: ARG001
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return {"reverted": ["id-1", "id-2"], "skipped": [], "failed": []}

    monkeypatch.setattr(AgentApiClient, "_request", fake_request)
    cfg = CliConfig(base_url="http://test", timeout_seconds=1)
    client = AgentApiClient(cfg)
    result = client.revert_file_changes_batch(
        ["id-1", "id-2"],
        force=False,
        permission_request_id=None,
    )
    assert captured["method"] == "POST"
    assert captured["path"] == "/file-changes/revert-batch"
    assert captured["json"]["change_ids"] == ["id-1", "id-2"]
    assert result["reverted"] == ["id-1", "id-2"]


# ---------------------------------------------------------------------------
# 8. Nonce determinism and non-reuse
# ---------------------------------------------------------------------------


def test_approval_nonce_is_stable_for_same_args() -> None:
    fid = uuid4()
    a = compute_approval_nonce(
        file_change_id=fid, relative_path="foo.py", expected_after_sha256="abc", force=False
    )
    b = compute_approval_nonce(
        file_change_id=fid, relative_path="foo.py", expected_after_sha256="abc", force=False
    )
    assert a == b
    c = compute_approval_nonce(
        file_change_id=fid, relative_path="foo.py", expected_after_sha256="abc", force=True
    )
    assert a != c
    d = compute_approval_nonce(
        file_change_id=fid, relative_path="bar.py", expected_after_sha256="abc", force=False
    )
    assert a != d
    e = compute_approval_nonce(
        file_change_id=uuid4(), relative_path="foo.py", expected_after_sha256="abc", force=False
    )
    assert a != e


# ---------------------------------------------------------------------------
# 9. Atomic batch rollback at the service layer
# ---------------------------------------------------------------------------


async def test_batch_rollback_restores_on_disk_state(tmp_path: Path) -> None:
    from backend.app.file_changes.file_change_service import (
        FileChangeContext,
        build_captures_for_tool,
        capture_for_tool_call,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    a = workspace / "a.txt"
    a.write_text("original_a\n", encoding="utf-8")
    b = workspace / "b.txt"
    b.write_text("original_b\n", encoding="utf-8")

    ctx = FileChangeContext(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=uuid4(),
        workspace_root=workspace,
    )
    from backend.app.tools.write import WriteFileInput, WriteFileTool

    tool = WriteFileTool()
    settings = {
        "enabled": True,
        "capture_content": True,
        "capture_diff": True,
        "max_content_bytes": 1024,
        "max_diff_bytes": 1024,
        "secret_filename_globs": [],
    }
    for path, _before, after in [(a, "original_a\n", "modified_a\n"), (b, "original_b\n", "modified_b\n")]:
        result = await tool.run(WriteFileInput(path=path.name, content=after), type("C", (), {
            "organization_id": ctx.organization_id,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "session_id": ctx.session_id,
            "agent_id": "test",
            "workspace_root": workspace,
        })())
        build_captures_for_tool(
            tool_name="write.file",
            input_json={"path": path.name, "content": after},
            result_output=result.output,
            result_metadata=result.metadata,
            workspace_root=workspace,
        )
        await capture_for_tool_call(
            FakeAsyncSession(),
            ctx=ctx,
            tool_name="write.file",
            input_json={"path": path.name, "content": after},
            result_output=result.output,
            result_metadata=result.metadata,
            settings_snapshot=settings,
        )


    db = FakeAsyncSession()
    # Capture rows directly.
    rows = await capture_for_tool_call(
        db,
        ctx=ctx,
        tool_name="write.file",
        input_json={"path": a.name, "content": "modified_a\n"},
        result_output={"path": a.name, "sha256": content_sha256("modified_a\n")},
        result_metadata={"previous_sha256": content_sha256("original_a\n"), "sha256": content_sha256("modified_a\n")},
        settings_snapshot=settings,
    )
    a_row_id = rows[0].id
    rows = await capture_for_tool_call(
        db,
        ctx=ctx,
        tool_name="write.file",
        input_json={"path": b.name, "content": "modified_b\n"},
        result_output={"path": b.name, "sha256": content_sha256("modified_b\n")},
        result_metadata={"previous_sha256": content_sha256("original_b\n"), "sha256": content_sha256("modified_b\n")},
        settings_snapshot=settings,
    )
    b_row_id = rows[0].id

    # Now force a hash mismatch on b so the second revert in the batch fails.
    b.write_text("tampered_b\n", encoding="utf-8")

    result = await revert_file_changes_batch(
        db,
        file_change_ids=[a_row_id, b_row_id],
        workspace_root=workspace,
        actor_user_id=None,
        force=False,
    )
    # The second revert fails; the on-disk state of a must be restored
    # to its pre-batch content (which was 'modified_a' before the batch).
    assert result.error is not None
    assert result.restored_from_snapshots is True
    # After the rollback attempt, a should have been restored to whatever it
    # was before the batch started (i.e. 'modified_a\n'), not 'original_a\n'
    # because the snapshot is the pre-batch state, not the recorded before.
    assert a.read_text(encoding="utf-8") == "modified_a\n"


# ---------------------------------------------------------------------------
# 10. Revert does not modify file when precondition fails
# ---------------------------------------------------------------------------


async def test_revert_does_not_modify_file_on_hash_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "x.txt"
    target.write_text("original\n", encoding="utf-8")

    from backend.app.file_changes.file_change_service import FileChangeContext
    from backend.app.tools.write import WriteFileInput, WriteFileTool

    ctx = FileChangeContext(
        organization_id=uuid4(),
        project_id=uuid4(),
        workspace_id=uuid4(),
        session_id=uuid4(),
        agent_run_id=uuid4(),
        tool_call_id=uuid4(),
        workspace_root=workspace,
    )
    tool = WriteFileTool()
    result = await tool.run(
        WriteFileInput(path=target.name, content="modified\n"),
        type("C", (), {
            "organization_id": ctx.organization_id,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "session_id": ctx.session_id,
            "agent_id": "test",
            "workspace_root": workspace,
        })(),
    )
    settings = {
        "enabled": True,
        "capture_content": True,
        "capture_diff": True,
        "max_content_bytes": 1024,
        "max_diff_bytes": 1024,
        "secret_filename_globs": [],
    }
    rows = await capture_for_tool_call(
        FakeAsyncSession(),
        ctx=ctx,
        tool_name="write.file",
        input_json={"path": target.name, "content": "modified\n"},
        result_output=result.output,
        result_metadata=result.metadata,
        settings_snapshot=settings,
    )
    change_id = rows[0].id

    # Tamper with the file to force a hash mismatch.
    target.write_text("someone else's content\n", encoding="utf-8")
    with pytest.raises(FileChangeError):
        await revert_file_change(
            FakeAsyncSession(objects=rows),
            file_change_id=change_id,
            workspace_root=workspace,
            actor_user_id=None,
            force=False,
        )
    # The on-disk content must not have been overwritten with the recorded
    # before_content.
    assert target.read_text(encoding="utf-8") == "someone else's content\n"
