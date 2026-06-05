"""runtime spine event and call metadata

Revision ID: 202606050002
Revises: 202606050001
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050002"
down_revision: str | None = "202606050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS duration_ms integer;
        ALTER TABLE model_calls ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id);
        ALTER TABLE model_calls ADD COLUMN IF NOT EXISTS workspace_id uuid REFERENCES workspaces(id);
        ALTER TABLE system_events ADD COLUMN IF NOT EXISTS agent_run_id uuid REFERENCES agent_runs(id);
        ALTER TABLE system_events ADD COLUMN IF NOT EXISTS tool_call_id uuid REFERENCES tool_calls(id);

        CREATE INDEX IF NOT EXISTS ix_sessions_status_updated ON sessions(status, updated_at);
        CREATE INDEX IF NOT EXISTS ix_agent_runs_status_created ON agent_runs(status, created_at);
        CREATE INDEX IF NOT EXISTS ix_tool_calls_status_created ON tool_calls(status, created_at);
        CREATE INDEX IF NOT EXISTS ix_model_calls_status_created ON model_calls(status, created_at);
        CREATE INDEX IF NOT EXISTS ix_model_calls_agent_run_created ON model_calls(agent_run_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_system_events_agent_run_created ON system_events(agent_run_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_system_events_tool_call_created ON system_events(tool_call_id, created_at);

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_tool_calls_permission_request_id'
          ) THEN
            ALTER TABLE tool_calls
              ADD CONSTRAINT fk_tool_calls_permission_request_id
              FOREIGN KEY (permission_request_id) REFERENCES permission_requests(id) ON DELETE SET NULL;
          END IF;
        END
        $$;

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_permission_requests_tool_call_id'
          ) THEN
            ALTER TABLE permission_requests
              ADD CONSTRAINT fk_permission_requests_tool_call_id
              FOREIGN KEY (tool_call_id) REFERENCES tool_calls(id) ON DELETE SET NULL;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE permission_requests DROP CONSTRAINT IF EXISTS fk_permission_requests_tool_call_id;
        ALTER TABLE tool_calls DROP CONSTRAINT IF EXISTS fk_tool_calls_permission_request_id;

        DROP INDEX IF EXISTS ix_system_events_tool_call_created;
        DROP INDEX IF EXISTS ix_system_events_agent_run_created;
        DROP INDEX IF EXISTS ix_model_calls_agent_run_created;
        DROP INDEX IF EXISTS ix_model_calls_status_created;
        DROP INDEX IF EXISTS ix_tool_calls_status_created;
        DROP INDEX IF EXISTS ix_agent_runs_status_created;
        DROP INDEX IF EXISTS ix_sessions_status_updated;

        ALTER TABLE system_events DROP COLUMN IF EXISTS tool_call_id;
        ALTER TABLE system_events DROP COLUMN IF EXISTS agent_run_id;
        ALTER TABLE model_calls DROP COLUMN IF EXISTS workspace_id;
        ALTER TABLE model_calls DROP COLUMN IF EXISTS project_id;
        ALTER TABLE tool_calls DROP COLUMN IF EXISTS duration_ms;
        """
    )
