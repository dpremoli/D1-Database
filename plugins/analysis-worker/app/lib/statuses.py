"""Canonical test_sessions.status vocabulary.

This MUST stay in sync with the CHECK constraint defined in
db/migrations/20260619000013_status_vocabulary.sql. The unit test
test_statuses.py asserts that every status this worker emits is a member of
ALLOWED_STATUSES.
"""

ALLOWED_STATUSES: frozenset[str] = frozenset(
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

# Statuses this worker emits.
STATUS_ANALYSING = "analysing"
STATUS_ANALYSED = "analysed"
STATUS_FAILED = "failed"
