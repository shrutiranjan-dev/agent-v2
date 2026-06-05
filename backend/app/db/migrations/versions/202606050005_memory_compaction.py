"""memory and compaction schema

Revision ID: 202606050005
Revises: 202606050004
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050005"
down_revision: str | None = "202606050004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS session_summaries (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
          summary_type varchar(40) NOT NULL,
          content text NOT NULL,
          source_message_start_id uuid REFERENCES messages(id) ON DELETE SET NULL,
          source_message_end_id uuid REFERENCES messages(id) ON DELETE SET NULL,
          source_message_count integer NOT NULL DEFAULT 0,
          token_estimate integer,
          char_count integer NOT NULL DEFAULT 0,
          model varchar(160),
          status varchar(40) NOT NULL DEFAULT 'active',
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_session_summaries_session ON session_summaries(session_id);
        CREATE INDEX IF NOT EXISTS ix_session_summaries_status ON session_summaries(status);
        CREATE INDEX IF NOT EXISTS ix_session_summaries_created ON session_summaries(created_at);

        ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS source_type varchar(80);
        UPDATE memory_items SET source_type = COALESCE(source_type, kind, 'project_note');
        ALTER TABLE memory_items ALTER COLUMN source_type SET NOT NULL;
        ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS source_id varchar(160);
        ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS content_hash varchar(64);
        UPDATE memory_items
          SET content_hash = encode(digest(coalesce(content, '') || ':' || id::text, 'sha256'), 'hex')
          WHERE content_hash IS NULL;
        ALTER TABLE memory_items ALTER COLUMN content_hash SET NOT NULL;
        ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding_model varchar(160);
        ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS visibility varchar(40) NOT NULL DEFAULT 'private';
        ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS status varchar(40) NOT NULL DEFAULT 'active';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_items_content_hash ON memory_items(content_hash);
        CREATE INDEX IF NOT EXISTS ix_memory_items_project_workspace_session ON memory_items(project_id, workspace_id, session_id);
        CREATE INDEX IF NOT EXISTS ix_memory_items_source_type ON memory_items(source_type);
        CREATE INDEX IF NOT EXISTS ix_memory_items_status ON memory_items(status);
        CREATE INDEX IF NOT EXISTS ix_memory_items_content_hash ON memory_items(content_hash);

        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS ix_memory_items_embedding_vector ON memory_items USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100) WHERE embedding IS NOT NULL';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_memory_items_embedding_vector;
        DROP INDEX IF EXISTS ix_memory_items_content_hash;
        DROP INDEX IF EXISTS ix_memory_items_status;
        DROP INDEX IF EXISTS ix_memory_items_source_type;
        DROP INDEX IF EXISTS ix_memory_items_project_workspace_session;
        DROP INDEX IF EXISTS uq_memory_items_content_hash;
        ALTER TABLE memory_items DROP COLUMN IF EXISTS status;
        ALTER TABLE memory_items DROP COLUMN IF EXISTS visibility;
        ALTER TABLE memory_items DROP COLUMN IF EXISTS embedding_model;
        ALTER TABLE memory_items DROP COLUMN IF EXISTS content_hash;
        ALTER TABLE memory_items DROP COLUMN IF EXISTS source_id;
        ALTER TABLE memory_items DROP COLUMN IF EXISTS source_type;
        DROP INDEX IF EXISTS ix_session_summaries_created;
        DROP INDEX IF EXISTS ix_session_summaries_status;
        DROP INDEX IF EXISTS ix_session_summaries_session;
        DROP TABLE IF EXISTS session_summaries;
        """
    )
