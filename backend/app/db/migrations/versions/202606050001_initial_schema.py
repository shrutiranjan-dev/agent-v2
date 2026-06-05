"""initial production schema

Revision ID: 202606050001
Revises:
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
    op.execute(
        """
        CREATE TABLE organizations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          name varchar(255) NOT NULL,
          slug varchar(120) NOT NULL UNIQUE,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE users (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          email varchar(320) NOT NULL,
          display_name varchar(255) NOT NULL,
          role varchar(50) NOT NULL DEFAULT 'owner',
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_users_org_email UNIQUE (organization_id, email)
        );

        CREATE TABLE projects (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          name varchar(255) NOT NULL,
          slug varchar(120) NOT NULL,
          description text,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_projects_org_slug UNIQUE (organization_id, slug)
        );

        CREATE TABLE workspaces (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name varchar(255) NOT NULL,
          root_path text NOT NULL,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_workspaces_project_name UNIQUE (project_id, name)
        );

        CREATE TABLE sessions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          created_by_user_id uuid NOT NULL REFERENCES users(id),
          title varchar(255) NOT NULL,
          agent_id varchar(80) NOT NULL DEFAULT 'build',
          model_provider varchar(80) NOT NULL DEFAULT 'ollama',
          model_name varchar(160) NOT NULL,
          status varchar(40) NOT NULL DEFAULT 'idle',
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_sessions_workspace_updated ON sessions(workspace_id, updated_at);
        CREATE INDEX ix_sessions_org_project ON sessions(organization_id, project_id);

        CREATE TABLE messages (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          role varchar(40) NOT NULL,
          content text NOT NULL,
          parts jsonb NOT NULL DEFAULT '[]'::jsonb,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_messages_session_created ON messages(session_id, created_at);
        CREATE INDEX ix_messages_session_role ON messages(session_id, role);

        CREATE TABLE agent_runs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          agent_id varchar(80) NOT NULL,
          model_provider varchar(80) NOT NULL,
          model_name varchar(160) NOT NULL,
          status varchar(40) NOT NULL DEFAULT 'running',
          step_count integer NOT NULL DEFAULT 0,
          error text,
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_agent_runs_session_created ON agent_runs(session_id, created_at);

        CREATE TABLE tool_calls (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          agent_run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
          agent_id varchar(80) NOT NULL,
          tool_name varchar(120) NOT NULL,
          input_json jsonb NOT NULL,
          input_hash varchar(64) NOT NULL,
          status varchar(40) NOT NULL DEFAULT 'pending',
          output_json jsonb,
          error text,
          permission_request_id uuid,
          started_at timestamptz,
          completed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_tool_calls_session_created ON tool_calls(session_id, created_at);
        CREATE INDEX ix_tool_calls_loop_guard ON tool_calls(session_id, agent_id, tool_name, input_hash);

        CREATE TABLE permission_requests (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          agent_run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
          tool_call_id uuid,
          permission_key varchar(120) NOT NULL,
          resource text NOT NULL,
          action varchar(20) NOT NULL DEFAULT 'ask',
          status varchar(30) NOT NULL DEFAULT 'pending',
          input_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          requested_by_user_id uuid REFERENCES users(id),
          resolved_by_user_id uuid REFERENCES users(id),
          resolved_at timestamptz,
          resolution_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_permission_requests_session_status ON permission_requests(session_id, status);
        CREATE INDEX ix_permission_requests_org_status ON permission_requests(organization_id, status);

        CREATE TABLE model_providers (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          name varchar(80) NOT NULL,
          endpoint text NOT NULL,
          status varchar(40) NOT NULL DEFAULT 'unknown',
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_model_providers_org_name UNIQUE (organization_id, name)
        );

        CREATE TABLE model_calls (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          session_id uuid REFERENCES sessions(id),
          agent_run_id uuid REFERENCES agent_runs(id),
          provider varchar(80) NOT NULL,
          model varchar(160) NOT NULL,
          prompt_tokens integer NOT NULL DEFAULT 0,
          completion_tokens integer NOT NULL DEFAULT 0,
          latency_ms integer,
          status varchar(40) NOT NULL,
          error text,
          request_json jsonb,
          response_json jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_model_calls_session_created ON model_calls(session_id, created_at);

        CREATE TABLE artifacts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid REFERENCES projects(id),
          workspace_id uuid REFERENCES workspaces(id),
          session_id uuid REFERENCES sessions(id),
          tool_call_id uuid REFERENCES tool_calls(id),
          name varchar(255) NOT NULL,
          kind varchar(80) NOT NULL,
          bucket varchar(120) NOT NULL,
          object_key text NOT NULL,
          content_type varchar(255),
          size_bytes integer,
          checksum varchar(128),
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_artifacts_session_created ON artifacts(session_id, created_at);

        CREATE TABLE audit_logs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          actor_user_id uuid REFERENCES users(id),
          action varchar(160) NOT NULL,
          resource_type varchar(120) NOT NULL,
          resource_id varchar(120),
          status varchar(40) NOT NULL DEFAULT 'ok',
          ip_address varchar(80),
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_logs_org_created ON audit_logs(organization_id, created_at);

        CREATE TABLE memory_items (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid REFERENCES projects(id),
          workspace_id uuid REFERENCES workspaces(id),
          session_id uuid REFERENCES sessions(id),
          kind varchar(80) NOT NULL,
          content text NOT NULL,
          embedding vector(1536),
          qdrant_collection varchar(120),
          qdrant_point_id varchar(120),
          neo4j_node_id varchar(120),
          score double precision,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_memory_items_scope ON memory_items(organization_id, project_id, workspace_id);

        CREATE TABLE plugins (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          name varchar(160) NOT NULL,
          version varchar(80),
          source text NOT NULL,
          enabled boolean NOT NULL DEFAULT false,
          status varchar(40) NOT NULL DEFAULT 'registered',
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_plugins_org_name UNIQUE (organization_id, name)
        );

        CREATE TABLE mcp_servers (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          name varchar(160) NOT NULL,
          server_type varchar(40) NOT NULL,
          command_json jsonb,
          url text,
          headers_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          enabled boolean NOT NULL DEFAULT false,
          status varchar(40) NOT NULL DEFAULT 'registered',
          last_error text,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_mcp_servers_org_name UNIQUE (organization_id, name)
        );

        CREATE TABLE system_events (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid REFERENCES organizations(id),
          project_id uuid REFERENCES projects(id),
          workspace_id uuid REFERENCES workspaces(id),
          session_id uuid REFERENCES sessions(id),
          event_type varchar(160) NOT NULL,
          severity varchar(40) NOT NULL DEFAULT 'info',
          payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_system_events_session_created ON system_events(session_id, created_at);
        CREATE INDEX ix_system_events_org_created ON system_events(organization_id, created_at);
        CREATE INDEX ix_system_events_type_created ON system_events(event_type, created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS system_events;
        DROP TABLE IF EXISTS mcp_servers;
        DROP TABLE IF EXISTS plugins;
        DROP TABLE IF EXISTS memory_items;
        DROP TABLE IF EXISTS audit_logs;
        DROP TABLE IF EXISTS artifacts;
        DROP TABLE IF EXISTS model_calls;
        DROP TABLE IF EXISTS model_providers;
        DROP TABLE IF EXISTS permission_requests;
        DROP TABLE IF EXISTS tool_calls;
        DROP TABLE IF EXISTS agent_runs;
        DROP TABLE IF EXISTS messages;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS workspaces;
        DROP TABLE IF EXISTS projects;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS organizations;
        """
    )

