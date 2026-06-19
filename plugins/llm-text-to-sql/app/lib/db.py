"""Read-only database access for the text-to-SQL layer.

Connects with ``LLM_DATABASE_URL`` — a DSN for a login role that inherits the
``d1_llm_readonly`` group role (see docs/runbooks/text-to-sql.md). That role is
``default_transaction_read_only`` with a statement timeout, so even a guard
bypass cannot mutate data or run a runaway query. We additionally pin each
transaction read-only here as belt-and-suspenders.
"""

import os

import psycopg
from psycopg.rows import dict_row

LLM_DATABASE_URL: str = os.getenv("LLM_DATABASE_URL", "")
# Per-connection statement timeout (ms). Enforced here rather than relying on the
# d1_llm_readonly role's setting, because role-level SET values are not inherited
# by member login roles (see docs/runbooks/text-to-sql.md).
STATEMENT_TIMEOUT_MS: int = int(os.getenv("LLM_STATEMENT_TIMEOUT_MS", "5000"))


def _connect() -> psycopg.Connection:
    """Open a connection pinned read-only with a statement timeout.

    Defence-in-depth on top of the d1_llm_readonly grants: even if the login
    role is mis-provisioned, this connection cannot write or run unbounded.
    """
    if not LLM_DATABASE_URL:
        raise RuntimeError("LLM_DATABASE_URL is not configured")
    conn = psycopg.connect(LLM_DATABASE_URL, row_factory=dict_row)
    conn.read_only = True
    # SET does not accept bind parameters; STATEMENT_TIMEOUT_MS is coerced to int.
    conn.execute(f"SET statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
    return conn


def run_select(sql: str) -> list[dict]:
    """Execute an already-guarded read-only query and return rows as dicts."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def fetch_query_targets() -> list[dict]:
    """Return the allow-listed views and their descriptions (the LLM menu)."""
    return run_select(
        "SELECT view_name, description FROM v_llm_query_targets ORDER BY view_name"
    )


def fetch_dictionary(views: list[str]) -> list[dict]:
    """Return the column dictionary rows for the given object names."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT object_name, object_comment, column_name, data_type,
                       column_comment
                FROM v_schema_dictionary
                WHERE object_name = ANY(%s)
                ORDER BY object_name, column_position
                """,
                (views,),
            )
            return cur.fetchall()


def semantic_search(query_embedding: list[float], limit: int = 5) -> list[dict]:
    """Return the note rows most similar to *query_embedding* (cosine distance)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_table, source_id, source_column, content_text,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM semantic_embeddings
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, query_embedding, limit),
            )
            return cur.fetchall()
