"""SQL-guard tests — the security-critical allow/deny matrix.

If any DENY case starts passing validation, the injection boundary is broken.
"""

import pytest

from app.lib.sql_guard import (
    DEFAULT_ROW_LIMIT,
    SqlGuardError,
    guard,
    message_only,
    validate,
)

ALLOW = [
    "SELECT * FROM v_complete_sample_history",
    "SELECT mass_grams FROM v_complete_sample_history WHERE mass_grams > 10",
    "select count(*) from v_test_sessions_full",
    "SELECT * FROM v_complete_sample_history WHERE sample_code = 'a' LIMIT 5",
    # Base tables are now readable (broad read surface, ADR-0009 revisited).
    "SELECT * FROM physical_samples",
    "SELECT machining_feed_mm_per_rev, machining_spindle_speed_rpm "
    "FROM manufacturing_operations WHERE machining_feed_mm_per_rev IS NOT NULL",
    "SELECT * FROM audit_logs",
    # Benign Directus metadata is readable.
    "SELECT collection FROM directus_activity",
    # CTE + base table.
    "WITH heavy AS (SELECT sample_id FROM physical_samples) "
    "SELECT * FROM v_manufacturing_operations_full "
    "WHERE sample_id IN (SELECT sample_id FROM heavy)",
    # UNION across a view and a base table.
    "SELECT sample_code FROM v_complete_sample_history "
    "UNION SELECT sample_code FROM physical_samples",
    # Join a base table to a view (the feed/speed use case).
    "SELECT o.machining_feed_mm_per_rev FROM manufacturing_operations o "
    "JOIN v_complete_sample_history v ON v.sample_id = o.sample_id",
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
    ("select_into", "SELECT * INTO evil FROM v_complete_sample_history"),
    ("stacked", "SELECT 1 FROM v_complete_sample_history; DROP TABLE physical_samples"),
    (
        "stacked_update",
        "SELECT 1 FROM v_test_sessions_full; UPDATE physical_samples SET notes='x'",
    ),
    # Credential / auth / system relations are denied even for read.
    ("directus_users", "SELECT * FROM directus_users"),
    ("directus_sessions", "SELECT token FROM directus_sessions"),
    ("directus_settings", "SELECT ai_openai_api_key FROM directus_settings"),
    ("directus_flows", "SELECT * FROM directus_flows"),
    ("directus_operations", "SELECT * FROM directus_operations"),
    ("directus_permissions", "SELECT * FROM directus_permissions"),
    ("schema_migrations", "SELECT * FROM schema_migrations"),
    # Unknown/future directus_* is denied by default.
    ("unknown_directus", "SELECT * FROM directus_super_secret"),
    ("comment_hidden_secret", "SELECT * FROM /* */ directus_users"),
    ("mixed_allow_and_secret", "SELECT * FROM v_complete_sample_history, directus_users"),
    ("cte_then_secret", "WITH x AS (SELECT 1) SELECT * FROM directus_sessions"),
    (
        "join_to_secret",
        "SELECT v.sample_code FROM v_complete_sample_history v "
        "JOIN directus_users u ON true",
    ),
    # Postgres system catalogs stay blocked.
    ("information_schema", "SELECT * FROM information_schema.tables"),
    ("pg_catalog", "SELECT * FROM pg_catalog.pg_roles"),
    ("pg_authid", "SELECT * FROM pg_authid"),
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


# --- message-only detection (greetings / off-topic -> plain reply) ---


def test_message_only_returns_text_for_table_free_select():
    assert message_only("SELECT 'hi there' AS note") == "hi there"
    assert message_only("SELECT 'hi there' AS note;") == "hi there"


def test_message_only_none_for_real_query():
    assert message_only("SELECT count(*) FROM v_complete_sample_history") is None


def test_message_only_none_for_unsafe_or_stacked():
    assert message_only("DELETE FROM physical_samples") is None
    assert message_only("SELECT 'x' AS note; DROP TABLE physical_samples") is None
    assert message_only("") is None
