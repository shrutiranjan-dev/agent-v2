"""mcp and plugin foundations

Revision ID: 202606050007
Revises: 202606050006
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050007"
down_revision: str | None = "202606050006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE plugins ALTER COLUMN organization_id DROP NOT NULL;
        ALTER TABLE plugins ALTER COLUMN source DROP NOT NULL;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id) ON DELETE SET NULL;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS manifest_path text;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS source_type varchar(40) NOT NULL DEFAULT 'local';
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS trusted boolean NOT NULL DEFAULT false;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS capabilities_json jsonb NOT NULL DEFAULT '[]'::jsonb;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS hooks_json jsonb NOT NULL DEFAULT '[]'::jsonb;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS last_loaded_at timestamptz;
        ALTER TABLE plugins ADD COLUMN IF NOT EXISTS last_error text;
        UPDATE plugins SET status = 'disabled' WHERE status = 'registered';
        CREATE INDEX IF NOT EXISTS ix_plugins_workspace ON plugins(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_plugins_status ON plugins(status);
        CREATE INDEX IF NOT EXISTS ix_plugins_enabled ON plugins(enabled);

        CREATE TABLE IF NOT EXISTS plugin_tools (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          plugin_id uuid NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
          name varchar(160) NOT NULL,
          full_name varchar(260) NOT NULL,
          description text,
          input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
          risk_level varchar(40) NOT NULL DEFAULT 'medium',
          enabled boolean NOT NULL DEFAULT false,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_plugin_tools_full_name UNIQUE (full_name)
        );
        CREATE INDEX IF NOT EXISTS ix_plugin_tools_plugin ON plugin_tools(plugin_id);
        CREATE INDEX IF NOT EXISTS ix_plugin_tools_enabled ON plugin_tools(enabled);

        ALTER TABLE mcp_servers ALTER COLUMN organization_id DROP NOT NULL;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id) ON DELETE SET NULL;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS command text;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS args_json jsonb NOT NULL DEFAULT '[]'::jsonb;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS env_json jsonb NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS trusted boolean NOT NULL DEFAULT false;
        ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS last_connected_at timestamptz;
        UPDATE mcp_servers SET status = 'disabled' WHERE status = 'registered';
        CREATE INDEX IF NOT EXISTS ix_mcp_servers_workspace ON mcp_servers(workspace_id);
        CREATE INDEX IF NOT EXISTS ix_mcp_servers_name ON mcp_servers(name);
        CREATE INDEX IF NOT EXISTS ix_mcp_servers_status ON mcp_servers(status);
        CREATE INDEX IF NOT EXISTS ix_mcp_servers_enabled ON mcp_servers(enabled);

        CREATE TABLE IF NOT EXISTS mcp_tools (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          mcp_server_id uuid NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
          name varchar(160) NOT NULL,
          full_name varchar(260) NOT NULL,
          description text,
          input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
          risk_level varchar(40) NOT NULL DEFAULT 'medium',
          enabled boolean NOT NULL DEFAULT false,
          discovered_at timestamptz,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_mcp_tools_full_name UNIQUE (full_name)
        );
        CREATE INDEX IF NOT EXISTS ix_mcp_tools_server ON mcp_tools(mcp_server_id);
        CREATE INDEX IF NOT EXISTS ix_mcp_tools_full_name ON mcp_tools(full_name);
        CREATE INDEX IF NOT EXISTS ix_mcp_tools_enabled ON mcp_tools(enabled);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_mcp_tools_enabled;
        DROP INDEX IF EXISTS ix_mcp_tools_full_name;
        DROP INDEX IF EXISTS ix_mcp_tools_server;
        DROP TABLE IF EXISTS mcp_tools;
        DROP INDEX IF EXISTS ix_mcp_servers_enabled;
        DROP INDEX IF EXISTS ix_mcp_servers_status;
        DROP INDEX IF EXISTS ix_mcp_servers_name;
        DROP INDEX IF EXISTS ix_mcp_servers_workspace;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS last_connected_at;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS trusted;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS env_json;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS args_json;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS command;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS workspace_id;
        ALTER TABLE mcp_servers DROP COLUMN IF EXISTS project_id;

        DROP INDEX IF EXISTS ix_plugin_tools_enabled;
        DROP INDEX IF EXISTS ix_plugin_tools_plugin;
        DROP TABLE IF EXISTS plugin_tools;
        DROP INDEX IF EXISTS ix_plugins_enabled;
        DROP INDEX IF EXISTS ix_plugins_status;
        DROP INDEX IF EXISTS ix_plugins_workspace;
        ALTER TABLE plugins DROP COLUMN IF EXISTS last_error;
        ALTER TABLE plugins DROP COLUMN IF EXISTS last_loaded_at;
        ALTER TABLE plugins DROP COLUMN IF EXISTS hooks_json;
        ALTER TABLE plugins DROP COLUMN IF EXISTS capabilities_json;
        ALTER TABLE plugins DROP COLUMN IF EXISTS trusted;
        ALTER TABLE plugins DROP COLUMN IF EXISTS source_type;
        ALTER TABLE plugins DROP COLUMN IF EXISTS manifest_path;
        ALTER TABLE plugins DROP COLUMN IF EXISTS workspace_id;
        ALTER TABLE plugins DROP COLUMN IF EXISTS project_id;
        """
    )
