"""SQL guard — the injection boundary for LLM-generated SQL.

The text-to-SQL flow lets a local LLM author SQL from a natural-language
question. That SQL is *never* trusted. This module is the primary defence (the
read-only ``d1_llm_readonly`` Postgres role is defence-in-depth):

  1. The statement must parse as exactly **one** SQL statement.
  2. It must be a read-only ``SELECT`` (optionally a ``WITH ... SELECT``). Any
     DML/DDL/utility node (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/GRANT/COPY/…)
     is rejected.
  3. It must not reference a **denied** relation — credential/secret tables, the
     Directus auth model, or any unknown ``directus_*`` system table. Everything
     else (all lab/domain tables and the ``v_*`` views) is readable. This mirrors
     the grants in ``db/migrations/…_llm_readonly_broad_read.sql`` (ADR-0009).
  4. A ``LIMIT`` is enforced by wrapping the query, so a model that forgets one
     cannot stream an unbounded result set.

Parsing is done with sqlglot (a real SQL parser), not regexes, so comment- and
whitespace-based evasion does not work.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

# The curated, denormalised views the prompt features first — the easy path for a
# small model. Not the security gate any more (base tables are readable too); the
# gate is the deny-list below.
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

# Relations the LLM may NEVER read: credentials/secrets, the Directus auth model,
# and migration bookkeeping. Mirrors the REVOKEs in
# db/migrations/…_llm_readonly_broad_read.sql — keep the two in sync.
DENIED_RELATIONS: frozenset[str] = frozenset(
    {
        # credentials / secrets
        "directus_users",
        "directus_sessions",
        "directus_settings",
        "directus_shares",
        "directus_deployments",
        # JSON config that can embed API keys / tokens
        "directus_flows",
        "directus_operations",
        # auth / permission model
        "directus_policies",
        "directus_permissions",
        "directus_access",
        "directus_roles",
        # migration bookkeeping
        "schema_migrations",
    }
)

# Benign Directus metadata that IS readable. Any other ``directus_*`` relation —
# including future/unknown ones — is denied by default, so a new Directus release
# cannot silently expose a secret table.
DIRECTUS_ALLOWED: frozenset[str] = frozenset(
    {
        "directus_collections",
        "directus_fields",
        "directus_relations",
        "directus_activity",
        "directus_revisions",
        "directus_files",
        "directus_folders",
        "directus_dashboards",
        "directus_panels",
        "directus_presets",
        "directus_translations",
        "directus_extensions",
        "directus_migrations",
        "directus_comments",
        "directus_versions",
        "directus_notifications",
    }
)


# Postgres system catalog schemas — never queryable (they can expose roles and,
# in principle, other instances' internals). Data questions never need them.
DENIED_SCHEMAS: frozenset[str] = frozenset({"pg_catalog", "information_schema"})


def is_denied_relation(name: str) -> bool:
    """True if the LLM must not read *name*.

    Denied: the explicit credential/auth deny-list, any ``directus_*`` table not
    on the benign-metadata allow-list (deny-by-default for system tables), and
    Postgres catalog relations (``pg_*``).
    """
    lowered = name.lower()
    if lowered in DENIED_RELATIONS:
        return True
    if lowered.startswith("directus_") and lowered not in DIRECTUS_ALLOWED:
        return True
    if lowered.startswith("pg_"):
        return True
    return False


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

    for table in tree.find_all(exp.Table):
        schema = (table.db or "").lower()
        if schema in DENIED_SCHEMAS:
            raise SqlGuardError(f"query references a system-catalog schema: {schema}")

    referenced = _referenced_tables(tree)
    if not referenced:
        raise SqlGuardError("query references no tables")

    denied = sorted(r for r in referenced if is_denied_relation(r))
    if denied:
        raise SqlGuardError(
            "query references blocked (credential/auth/system) relations: "
            + ", ".join(denied)
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


def message_only(sql: str) -> str | None:
    """Return the message text if *sql* is a safe, table-free constant SELECT.

    The model answers a greeting or an off-topic / unanswerable question with a
    table-free ``SELECT '…' AS note``. That legitimately references no table, so
    rather than reject it as "no tables" we surface the literal as a plain chat
    reply (no data table). Returns ``None`` for any real query (one that touches
    a table) or anything unsafe, stacked, or unparseable.
    """
    if not sql or not sql.strip():
        return None
    cleaned = _strip_trailing_semicolons(sql)
    if ";" in cleaned:  # stacked statements are never a friendly message
        return None
    try:
        tree = sqlglot.parse_one(cleaned, read="postgres")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(tree, exp.Select):
        return None
    if _referenced_tables(tree):  # a real query, not a message
        return None
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return None
    literal = tree.find(exp.Literal)
    if literal is not None and literal.is_string:
        return str(literal.this)
    return None


def guard(sql: str, row_limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Validate *sql* and return an execution-safe, row-limited version.

    The validated query is wrapped in an outer ``SELECT ... LIMIT`` so a result
    set is always bounded regardless of any (or no) inner LIMIT. Raises
    :class:`SqlGuardError` if validation fails.
    """
    validate(sql)
    inner = _strip_trailing_semicolons(sql)
    return f"SELECT * FROM (\n{inner}\n) AS _guarded LIMIT {int(row_limit)}"
