"""Canonical test_sessions.status vocabulary.

This MUST stay in sync with the CHECK constraint defined in
db/migrations/20260619000013_status_vocabulary.sql. Plugins derived from this
template should emit only members of ALLOWED_STATUSES.
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

# Statuses the example job emits.
STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"
