"""durable human input requests

Revision ID: 202606050004
Revises: 202606050003
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050004"
down_revision: str | None = "202606050003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS human_input_requests (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          run_id uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
          tool_call_id uuid NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE,
          question text NOT NULL,
          details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          status varchar(30) NOT NULL DEFAULT 'pending',
          answer text,
          answered_by_user_id uuid REFERENCES users(id),
          answered_at timestamptz,
          expires_at timestamptz,
          cancelled_at timestamptz,
          request_hash varchar(64) NOT NULL,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_human_input_requests_session ON human_input_requests(session_id);
        CREATE INDEX IF NOT EXISTS ix_human_input_requests_run ON human_input_requests(run_id);
        CREATE INDEX IF NOT EXISTS ix_human_input_requests_tool_call ON human_input_requests(tool_call_id);
        CREATE INDEX IF NOT EXISTS ix_human_input_requests_status ON human_input_requests(status);
        CREATE INDEX IF NOT EXISTS ix_human_input_requests_expires_at ON human_input_requests(expires_at);

        ALTER TABLE queue_jobs
          ADD COLUMN IF NOT EXISTS human_input_request_id uuid REFERENCES human_input_requests(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS ix_queue_jobs_human_input_request ON queue_jobs(human_input_request_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_queue_jobs_human_input_request;
        ALTER TABLE queue_jobs DROP COLUMN IF EXISTS human_input_request_id;
        DROP INDEX IF EXISTS ix_human_input_requests_expires_at;
        DROP INDEX IF EXISTS ix_human_input_requests_status;
        DROP INDEX IF EXISTS ix_human_input_requests_tool_call;
        DROP INDEX IF EXISTS ix_human_input_requests_run;
        DROP INDEX IF EXISTS ix_human_input_requests_session;
        DROP TABLE IF EXISTS human_input_requests;
        """
    )
