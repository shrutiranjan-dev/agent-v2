"""queue worker observability

Revision ID: 202606050009
Revises: 202606050008
Create Date: 2026-06-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050009"
down_revision: str | None = "202606050008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          worker_id varchar(255) NOT NULL,
          hostname varchar(255),
          process_id integer,
          status varchar(40) NOT NULL DEFAULT 'starting',
          current_queue_job_id uuid REFERENCES queue_jobs(id) ON DELETE SET NULL,
          current_run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
          claimed_jobs_count integer NOT NULL DEFAULT 0,
          completed_jobs_count integer NOT NULL DEFAULT 0,
          failed_jobs_count integer NOT NULL DEFAULT 0,
          last_heartbeat_at timestamptz NOT NULL DEFAULT now(),
          started_at timestamptz,
          stopped_at timestamptz,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_worker_heartbeats_worker_id UNIQUE (worker_id)
        );

        CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_status ON worker_heartbeats(status);
        CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_last_heartbeat ON worker_heartbeats(last_heartbeat_at);
        CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_current_queue_job ON worker_heartbeats(current_queue_job_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_worker_heartbeats_current_queue_job;
        DROP INDEX IF EXISTS ix_worker_heartbeats_last_heartbeat;
        DROP INDEX IF EXISTS ix_worker_heartbeats_status;
        DROP TABLE IF EXISTS worker_heartbeats;
        """
    )
