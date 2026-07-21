"""Postgres connection + batched upsert helpers."""
import logging

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)


def connect(database_url: str):
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    return conn


def execute_upsert(conn, sql: str, rows: list, page_size: int = 1000) -> int:
    """Bulk-insert `rows` via psycopg2.extras.execute_values.

    `sql` must be an INSERT ... VALUES %s ... statement (with ON CONFLICT
    handling baked in by the caller). Returns len(rows) sent -- ON CONFLICT
    DO NOTHING may silently skip some of those server-side, which is the
    expected idempotent-rerun behavior.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=page_size)
    return len(rows)


TRUNCATE_ALL_SQL = """
TRUNCATE TABLE
    fact_tool_events,
    fact_api_errors,
    fact_api_requests,
    fact_user_prompts,
    raw_events,
    dim_sessions,
    dim_employees
RESTART IDENTITY CASCADE;
"""


def truncate_all(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(TRUNCATE_ALL_SQL)
