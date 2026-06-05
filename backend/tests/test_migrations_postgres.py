import os
import subprocess

import psycopg
import pytest


@pytest.mark.skipif(
    not os.environ.get("AP_TEST_POSTGRES_URL"),
    reason="set AP_TEST_POSTGRES_URL to run real PostgreSQL migration smoke validation",
)
def test_alembic_upgrade_head_against_real_postgres() -> None:
    env = {**os.environ, "AP_DATABASE_URL": os.environ["AP_TEST_POSTGRES_URL"]}
    subprocess.run(
        [".venv/bin/alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        check=True,
        env=env,
        cwd=os.getcwd(),
    )
    url = env["AP_DATABASE_URL"].replace("+asyncpg", "")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select to_regclass('public.tool_calls'), to_regclass('public.system_events'), "
                "to_regclass('public.queue_jobs'), to_regclass('public.human_input_requests'), "
                "to_regclass('public.session_summaries'), to_regclass('public.memory_items'), "
                "to_regclass('public.code_files'), to_regclass('public.code_symbols'), "
                "to_regclass('public.code_references'), to_regclass('public.code_diagnostics')"
            )
            assert cur.fetchone() == (
                "tool_calls",
                "system_events",
                "queue_jobs",
                "human_input_requests",
                "session_summaries",
                "memory_items",
                "code_files",
                "code_symbols",
                "code_references",
                "code_diagnostics",
            )
            cur.execute("select extname from pg_extension where extname = 'vector'")
            assert cur.fetchone() == ("vector",)
