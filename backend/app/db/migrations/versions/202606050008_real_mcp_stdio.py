"""real MCP stdio transport fields

Revision ID: 202606050008
Revises: 202606050007
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606050008"
down_revision: str | None = "202606050007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS cwd text;")


def downgrade() -> None:
    op.execute("ALTER TABLE mcp_servers DROP COLUMN IF EXISTS cwd;")
