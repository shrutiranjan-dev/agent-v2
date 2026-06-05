"""code intelligence schema

Revision ID: 202606050006
Revises: 202606050005
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050006"
down_revision: str | None = "202606050005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS code_files (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
          workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
          path text NOT NULL,
          resolved_path text NOT NULL,
          language varchar(80),
          size_bytes integer NOT NULL DEFAULT 0,
          sha256 varchar(64) NOT NULL,
          line_count integer,
          indexed_at timestamptz,
          status varchar(40) NOT NULL DEFAULT 'active',
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_code_files_workspace_path UNIQUE (workspace_id, path)
        );
        CREATE INDEX IF NOT EXISTS ix_code_files_workspace_path ON code_files(workspace_id, path);
        CREATE INDEX IF NOT EXISTS ix_code_files_language ON code_files(language);
        CREATE INDEX IF NOT EXISTS ix_code_files_status ON code_files(status);
        CREATE INDEX IF NOT EXISTS ix_code_files_sha256 ON code_files(sha256);

        CREATE TABLE IF NOT EXISTS code_symbols (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          code_file_id uuid NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
          workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
          name text NOT NULL,
          kind varchar(40) NOT NULL DEFAULT 'unknown',
          language varchar(80),
          start_line integer NOT NULL,
          end_line integer,
          signature text,
          docstring text,
          parent_symbol_id uuid REFERENCES code_symbols(id) ON DELETE SET NULL,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_code_symbols_workspace_name ON code_symbols(workspace_id, name);
        CREATE INDEX IF NOT EXISTS ix_code_symbols_kind ON code_symbols(kind);
        CREATE INDEX IF NOT EXISTS ix_code_symbols_language ON code_symbols(language);
        CREATE INDEX IF NOT EXISTS ix_code_symbols_file ON code_symbols(code_file_id);

        CREATE TABLE IF NOT EXISTS code_references (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          symbol_id uuid REFERENCES code_symbols(id) ON DELETE SET NULL,
          code_file_id uuid NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
          reference_name text NOT NULL,
          reference_type varchar(40) NOT NULL DEFAULT 'unknown',
          line integer NOT NULL,
          "column" integer,
          snippet text,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_code_references_symbol ON code_references(symbol_id);
        CREATE INDEX IF NOT EXISTS ix_code_references_file ON code_references(code_file_id);
        CREATE INDEX IF NOT EXISTS ix_code_references_name ON code_references(reference_name);
        CREATE INDEX IF NOT EXISTS ix_code_references_type ON code_references(reference_type);

        CREATE TABLE IF NOT EXISTS code_diagnostics (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          code_file_id uuid NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
          workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
          source text NOT NULL,
          severity varchar(40) NOT NULL,
          code text,
          message text NOT NULL,
          line integer NOT NULL,
          "column" integer,
          end_line integer,
          end_column integer,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_code_diagnostics_workspace ON code_diagnostics(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_code_diagnostics_severity ON code_diagnostics(severity);
        CREATE INDEX IF NOT EXISTS ix_code_diagnostics_file ON code_diagnostics(code_file_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_code_diagnostics_file;
        DROP INDEX IF EXISTS ix_code_diagnostics_severity;
        DROP INDEX IF EXISTS ix_code_diagnostics_workspace;
        DROP TABLE IF EXISTS code_diagnostics;
        DROP INDEX IF EXISTS ix_code_references_type;
        DROP INDEX IF EXISTS ix_code_references_name;
        DROP INDEX IF EXISTS ix_code_references_file;
        DROP INDEX IF EXISTS ix_code_references_symbol;
        DROP TABLE IF EXISTS code_references;
        DROP INDEX IF EXISTS ix_code_symbols_file;
        DROP INDEX IF EXISTS ix_code_symbols_language;
        DROP INDEX IF EXISTS ix_code_symbols_kind;
        DROP INDEX IF EXISTS ix_code_symbols_workspace_name;
        DROP TABLE IF EXISTS code_symbols;
        DROP INDEX IF EXISTS ix_code_files_sha256;
        DROP INDEX IF EXISTS ix_code_files_status;
        DROP INDEX IF EXISTS ix_code_files_language;
        DROP INDEX IF EXISTS ix_code_files_workspace_path;
        DROP TABLE IF EXISTS code_files;
        """
    )
