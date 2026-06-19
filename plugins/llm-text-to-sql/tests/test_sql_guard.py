"""SQL-guard tests — the security-critical allow/deny matrix.

If any DENY case starts passing validation, the injection boundary is broken.
"""

import pytest

from app.lib.sql_guard import (
    DEFAULT_ROW_LIMIT,
    SqlGuardError,
    guard,
    validate,
)

ALLOW = [
    "SELECT * FROM v_complete_sample_history",
    "SELECT mass_grams FROM v_complete_sample_history WHERE mass_grams > 10",
    "select count(*) from v_test_sessions_full",
    "SELECT * FROM v_complete_sample_history WHERE sample_code = 'a' LIMIT 5",
    # CTE referencing only allow-listed views.
    """
    WITH heavy AS (
        SELECT sample_id FROM v_complete_sample_history WHERE mass_grams > 100
    )
    SELECT * FROM v_manufacturing_operations_full
    WHERE sample_id IN (SELECT sample_id FROM heavy)
    """,
    # UNION across allow-listed views.
    "SELECT sample_code FROM v_complete_sample_history "
    "UNION SELECT sample_code FROM v_test_sessions_full",
    # Join between two allow-listed views.
    "SELECT a.sample_code FROM v_complete_sample_history a "
    "JOIN v_test_sessions_full b ON a.sample_id = b.sample_id",
    "SELECT * FROM v_complete_sample_history;",  # single trailing semicolon ok
]

DENY = [
    ("empty", ""),
    ("whitespace", "   "),
    ("insert", "INSERT INTO physical_samples (sample_code) VALUES ('x')"),
    ("update", "UPDATE physical_samples SET notes = 'x'"),
    ("delete", "DELETE FROM physical_samples"),
    ("drop", "DROP TABLE physical_samples"),
    ("create", "CREATE TABLE evil (id int)"),
    ("alter", "ALTER TABLE physical_samples ADD COLUMN x int"),
    ("grant", "GRANT ALL ON physical_samples TO public"),
    ("truncate", "TRUNCATE physical_samples"),
    ("copy", "COPY physical_samples TO '/tmp/x'"),
    ("base_table", "SELECT * FROM physical_samples"),
    ("audit_table", "SELECT * FROM audit_logs"),
    ("information_schema", "SELECT * FROM information_schema.tables"),
    ("pg_catalog", "SELECT * FROM pg_catalog.pg_roles"),
    ("select_into", "SELECT * INTO evil FROM v_complete_sample_history"),
    ("stacked", "SELECT 1 FROM v_complete_sample_history; DROP TABLE physical_samples"),
    (
        "stacked_update",
        "SELECT 1 FROM v_test_sessions_full; UPDATE physical_samples SET notes='x'",
    ),
    ("comment_hidden_table", "SELECT * FROM /* */ audit_logs"),
    ("mixed_allow_and_deny", "SELECT * FROM v_complete_sample_history, audit_logs"),
    ("cte_then_base_table", "WITH x AS (SELECT 1) SELECT * FROM physical_samples"),
]


@pytest.mark.parametrize("sql", ALLOW)
def test_allowed_queries_pass(sql):
    validate(sql)  # must not raise


@pytest.mark.parametrize("name,sql", DENY, ids=[d[0] for d in DENY])
def test_disallowed_queries_rejected(name, sql):
    with pytest.raises(SqlGuardError):
        validate(sql)


def test_guard_wraps_with_limit():
    wrapped = guard("SELECT * FROM v_complete_sample_history", row_limit=50)
    assert wrapped.strip().endswith("LIMIT 50")
    assert "v_complete_sample_history" in wrapped


def test_guard_default_limit():
    wrapped = guard("SELECT * FROM v_test_sessions_full")
    assert f"LIMIT {DEFAULT_ROW_LIMIT}" in wrapped


def test_guard_rejects_before_wrapping():
    with pytest.raises(SqlGuardError):
        guard("DELETE FROM physical_samples")


def test_row_limit_is_integer_only():
    # A non-numeric limit must not flow into the SQL string.
    with pytest.raises(ValueError):
        guard("SELECT * FROM v_test_sessions_full", row_limit="5; DROP TABLE x")
