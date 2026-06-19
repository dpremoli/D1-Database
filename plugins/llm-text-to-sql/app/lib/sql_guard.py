"""SQL guard — the injection boundary for LLM-generated SQL.

The text-to-SQL flow lets a local LLM author SQL from a natural-language
question. That SQL is *never* trusted. This module is the primary defence (the
read-only ``d1_llm_readonly`` Postgres role is defence-in-depth):

  1. The statement must parse as exactly **one** SQL statement.
  2. It must be a read-only ``SELECT`` (optionally a ``WITH ... SELECT``). Any
     DML/DDL/utility node (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/GRANT/COPY/…)
     is rejected.
  3. Every table/view it references must be in the allow-list — the same set of
     ``v_*`` views exposed by ``v_llm_query_targets`` in the database.
  4. A ``LIMIT`` is enforced by wrapping the query, so a model that forgets one
     cannot stream an unbounded result set.

Parsing is done with sqlglot (a real SQL parser), not regexes, so comment- and
whitespace-based evasion does not work.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

# The allow-listed relations the LLM may read. Mirrors v_llm_query_targets in
# db/migrations/...ai_readiness.sql — keep the two in sync.
ALLOWED_RELATIONS: frozenset[str] = frozenset(
    {
        "v_complete_sample_history",
        "v_tooling_hierarchy",
        "v_sample_genealogy_flat",
        "v_manufacturing_operations_full",
        "v_stock_provenance",
        "v_test_sessions_full",
        "v_schema_dictionary",
        "v_llm_query_targets",
    }
)

# Expression classes that must never appear anywhere in the tree.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.AlterTable,
    exp.Command,  # raw/unknown utility statements (GRANT, VACUUM, ...)
    exp.Copy,
    exp.TruncateTable,
    exp.Set,
    exp.Merge,
    exp.Into,  # SELECT ... INTO writes a new table
)

DEFAULT_ROW_LIMIT = 200


class SqlGuardError(ValueError):
    """Raised when LLM-generated SQL fails a safety check."""


def _strip_trailing_semicolons(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def validate(sql: str) -> exp.Expression:
    """Parse *sql* and assert it is a single, read-only, allow-listed SELECT.

    Returns the parsed expression on success; raises :class:`SqlGuardError`
    otherwise. Does not execute anything.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("empty statement")

    cleaned = _strip_trailing_semicolons(sql)
    if ";" in cleaned:
        raise SqlGuardError("multiple statements are not allowed")

    try:
        statements = sqlglot.parse(cleaned, read="postgres")
    except Exception as exc:  # noqa: BLE001 — surface any parse failure uniformly
        raise SqlGuardError(f"could not parse SQL: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlGuardError("exactly one statement is required")

    tree = statements[0]

    # Top-level must be a SELECT or a set operation (UNION/INTERSECT/EXCEPT).
    if not isinstance(tree, exp.Select | exp.Union | exp.Subquery):
        raise SqlGuardError(
            f"only SELECT queries are allowed, got {type(tree).__name__}"
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlGuardError(f"forbidden statement element: {type(node).__name__}")

    referenced = _referenced_tables(tree)
    if not referenced:
        raise SqlGuardError("query references no tables")

    disallowed = sorted(referenced - ALLOWED_RELATIONS)
    if disallowed:
        raise SqlGuardError(
            "query references relations outside the allow-list: "
            + ", ".join(disallowed)
        )

    return tree


def _referenced_tables(tree: exp.Expression) -> set[str]:
    """Real (non-CTE) table/view names referenced anywhere in *tree*.

    CTE names defined with ``WITH`` are excluded — they are local aliases, not
    physical relations, and may legitimately shadow nothing in the allow-list.
    """
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in cte_names:
            tables.add(name)
    return tables


def guard(sql: str, row_limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Validate *sql* and return an execution-safe, row-limited version.

    The validated query is wrapped in an outer ``SELECT ... LIMIT`` so a result
    set is always bounded regardless of any (or no) inner LIMIT. Raises
    :class:`SqlGuardError` if validation fails.
    """
    validate(sql)
    inner = _strip_trailing_semicolons(sql)
    return f"SELECT * FROM (\n{inner}\n) AS _guarded LIMIT {int(row_limit)}"
