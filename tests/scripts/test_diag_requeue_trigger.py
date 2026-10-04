import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

DSN = os.environ.get("DATABASE_URL")


@pytest.fixture
def conn():
    if not DSN:
        pytest.skip("DATABASE_URL not set (needs a migrated Postgres)")
    try:
        c = psycopg2.connect(DSN)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    yield c
    c.rollback()
    c.close()


def _smallest_done_row(cur):
    # smallest cut (least likely to be mid-bake and holding a row lock)
    cur.execute(
        "SELECT id FROM machining_force_analysis WHERE diag_status='done' "
        "ORDER BY diag_points ASC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        pytest.skip("no baked diag row to test against")
    return row[0]


def test_editing_diag_recipe_requeues(conn):
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '3s'")
        rid = _smallest_done_row(cur)
        cur.execute(
            "UPDATE machining_force_analysis SET diag_recipe = '{\"steps\":[]}'::jsonb "
            "WHERE id = %s RETURNING diag_status",
            [rid],
        )
        assert cur.fetchone()[0] == "pending"
    conn.rollback()


def test_touching_unrelated_columns_does_not_requeue(conn):
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '3s'")
        rid = _smallest_done_row(cur)
        cur.execute(
            "UPDATE machining_force_analysis SET diag_points = diag_points "
            "WHERE id = %s RETURNING diag_status",
            [rid],
        )
        assert cur.fetchone()[0] == "done"
    conn.rollback()
