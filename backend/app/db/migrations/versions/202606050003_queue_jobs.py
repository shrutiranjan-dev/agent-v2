"""durable queue job tracking

Revision ID: 202606050003
Revises: 202606050002
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050003"
down_revision: str | None = "202606050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_jobs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          job_type varchar(40) NOT NULL,
          status varchar(40) NOT NULL DEFAULT 'queued',
          priority integer NOT NULL DEFAULT 100,
          run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
          session_id uuid REFERENCES sessions(id) ON DELETE CASCADE,
          permission_request_id uuid REFERENCES permission_requests(id) ON DELETE SET NULL,
          user_message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
          payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          idempotency_key varchar(255) NOT NULL,
          attempt_count integer NOT NULL DEFAULT 0,
          max_attempts integer NOT NULL DEFAULT 3,
          claimed_by varchar(255),
          claimed_at timestamptz,
          available_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          failed_at timestamptz,
          last_error text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_queue_jobs_idempotency_key UNIQUE (idempotency_key)
        );

        CREATE INDEX IF NOT EXISTS ix_queue_jobs_status_available ON queue_jobs(status, available_at);
        CREATE INDEX IF NOT EXISTS ix_queue_jobs_session ON queue_jobs(session_id);
        CREATE INDEX IF NOT EXISTS ix_queue_jobs_run ON queue_jobs(run_id);
        CREATE INDEX IF NOT EXISTS ix_queue_jobs_permission_request ON queue_jobs(permission_request_id);
        CREATE INDEX IF NOT EXISTS ix_queue_jobs_type ON queue_jobs(job_type);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_queue_jobs_type;
        DROP INDEX IF EXISTS ix_queue_jobs_permission_request;
        DROP INDEX IF EXISTS ix_queue_jobs_run;
        DROP INDEX IF EXISTS ix_queue_jobs_session;
        DROP INDEX IF EXISTS ix_queue_jobs_status_available;
        DROP TABLE IF EXISTS queue_jobs;
        """
    )
