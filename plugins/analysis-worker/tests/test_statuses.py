"""Guardrail: every status this worker emits must satisfy the DB CHECK constraint.

If this test fails, the worker is about to write a test_sessions.status value
that migration 20260619000013_status_vocabulary.sql will reject. Keep the mirror
constant below in sync with that migration.
"""

from app.lib.statuses import (
    ALLOWED_STATUSES,
    STATUS_ANALYSED,
    STATUS_ANALYSING,
    STATUS_FAILED,
)

# Mirror of the CHECK constraint in db/migrations/20260619000013_status_vocabulary.sql.
DB_CHECK_STATUSES = frozenset(
    {
        "registered",
        "pending_processing",
        "processing",
        "processed",
        "analysing",
        "analysed",
        "failed",
    }
)


def test_allowed_statuses_match_db_constraint():
    assert ALLOWED_STATUSES == DB_CHECK_STATUSES


def test_emitted_statuses_are_allowed():
    for status in (STATUS_ANALYSING, STATUS_ANALYSED, STATUS_FAILED):
        assert status in ALLOWED_STATUSES
