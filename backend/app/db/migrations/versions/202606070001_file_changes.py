"""file change tracking schema

Revision ID: 202606070001
Revises: 202606050009
Create Date: 2026-06-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606070001"
down_revision: str | None = "202606050009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS file_changes (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          agent_run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
          tool_call_id uuid REFERENCES tool_calls(id) ON DELETE SET NULL,
          tool_name varchar(80) NOT NULL,
          operation varchar(20) NOT NULL,
          relative_path text NOT NULL,
          resolved_path text NOT NULL,
          before_sha256 varchar(64),
          after_sha256 varchar(64),
          before_size_bytes integer,
          after_size_bytes integer,
          before_content text,
          after_content text,
          before_content_truncated boolean NOT NULL DEFAULT false,
          after_content_truncated boolean NOT NULL DEFAULT false,
          diff text,
          diff_truncated boolean NOT NULL DEFAULT false,
          additions integer NOT NULL DEFAULT 0,
          deletions integer NOT NULL DEFAULT 0,
          replacement_count integer NOT NULL DEFAULT 0,
          backup_path text,
          redacted boolean NOT NULL DEFAULT false,
          redaction_reason varchar(120),
          revertible boolean NOT NULL DEFAULT true,
          revert_status varchar(30) NOT NULL DEFAULT 'not_reverted',
          reverted_at timestamptz,
          reverted_by_user_id uuid REFERENCES users(id),
          revert_tool_call_id uuid REFERENCES tool_calls(id) ON DELETE SET NULL,
          revert_error text,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_file_changes_session_created ON file_changes(session_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_file_changes_session_path ON file_changes(session_id, relative_path);
        CREATE INDEX IF NOT EXISTS ix_file_changes_run_created ON file_changes(agent_run_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_file_changes_tool_call ON file_changes(tool_call_id);
        CREATE INDEX IF NOT EXISTS ix_file_changes_workspace_created ON file_changes(workspace_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_file_changes_org_created ON file_changes(organization_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_file_changes_revert_status ON file_changes(revert_status);
        CREATE INDEX IF NOT EXISTS ix_file_changes_tool_name ON file_changes(tool_name);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_file_changes_tool_name;
        DROP INDEX IF EXISTS ix_file_changes_revert_status;
        DROP INDEX IF EXISTS ix_file_changes_org_created;
        DROP INDEX IF EXISTS ix_file_changes_workspace_created;
        DROP INDEX IF EXISTS ix_file_changes_tool_call;
        DROP INDEX IF EXISTS ix_file_changes_run_created;
        DROP INDEX IF EXISTS ix_file_changes_session_path;
        DROP INDEX IF EXISTS ix_file_changes_session_created;
        DROP TABLE IF EXISTS file_changes;
        """
    )
