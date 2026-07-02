"""Builds the schema prompt the LLM sees.

Spec §6 calls for a "semantic schema dictionary" and a "views abstraction
layer" so a context-window-limited local LLM can synthesise correct SQL. We
assemble that prompt straight from the database (v_schema_dictionary), so it
always reflects the live schema and its COMMENTs — there is no second copy to
drift.

The read surface is broad (ADR-0009, revisited): every lab/domain table and the
curated v_* views, minus the credential/auth/system relations the guard denies.
Views are listed first because a small model writes better SQL against them.
"""

import os
import re
import time

from app.lib import db, sql_guard

# "Known values" legend cache — distinct categorical values change rarely, so we
# recompute at most once per TTL rather than on every request.
_KNOWN_TTL_S = int(os.getenv("LLM_KNOWN_VALUES_TTL_S", "600"))
_known_cache: dict = {"ts": 0.0, "text": ""}
# Columns whose values are free text / high-entropy identifiers — never list them.
_SKIP_VALUE_COLS = re.compile(
    r"note|comment|descr|url|metadata|pointer|hash|uid|email|legacy"
    r"|experiment_sheet|filename|path|_at$",
    re.I,
)


def _is_text_type(data_type: str) -> bool:
    dt = data_type.lower()
    return "char" in dt or dt in ("text", "citext", "name")


def _known_values_section(objects: dict) -> str:
    """A cached legend of distinct values for low-cardinality text columns.

    Solves value linking: the schema tells the model a column exists, but not
    that turning is stored as ``method_name = 'Turning'`` (subtype ``MT-F``) or
    Ti-6Al-4V as ``material_name = 'Ti-64'``. Listing the real values lets it
    filter correctly instead of guessing. Deduplicated by column name (views
    first); free-text and high-cardinality columns are skipped.
    """
    now = time.time()
    if _known_cache["ts"] > 0 and now - _known_cache["ts"] < _KNOWN_TTL_S:
        return _known_cache["text"]

    lines: list[str] = []
    seen: set[str] = set()
    for name in sorted(objects, key=lambda n: (not n.startswith("v_"), n)):
        for col in objects[name]["columns"]:
            cname = col["column_name"]
            if cname in seen or not _is_text_type(col["data_type"]):
                continue
            if _SKIP_VALUE_COLS.search(cname):
                continue
            values = db.distinct_values(name, cname)
            if not values or any(len(str(v)) > 60 for v in values):
                continue  # too many, unreadable, or free text
            seen.add(cname)
            lines.append(f"  {cname}: " + ", ".join(str(v) for v in values))

    text = (
        "\nKnown column values — use these EXACT strings in WHERE filters "
        "(do not invent variants):\n" + "\n".join(lines)
        if lines
        else ""
    )
    _known_cache["ts"] = now
    _known_cache["text"] = text
    return text

_SYSTEM_PREAMBLE = """\
You are a careful PostgreSQL analyst for a materials-science laboratory database.
Translate the user's question into ONE read-only SQL SELECT statement.

Hard rules:
- Output ONLY the SQL. No prose, no explanation, no markdown fences.
- SELECT queries only. Never INSERT, UPDATE, DELETE, or any DDL.
- Query ONLY the tables and views listed below. NEVER select a column from a
  relation that does not list that exact column beneath it.
- A v_* view is a convenient summary. Detailed process parameters — machining
  feed/speed/depth, additive laser power, sintering force, heat-treatment rates,
  etc. — live ONLY on the base tables (e.g. manufacturing_operations), NOT on any
  view. For those, query the base table. Use a v_* view only when it already
  lists every column you need.
- Column names already carry their units (e.g. mass_grams,
  machining_feed_mm_per_rev, machining_cutting_speed_m_per_min).
- When filtering on a value from the "Known column values" list, match it
  EXACTLY as written (e.g. material_name = 'Ti-64', method_name = 'Turning').
  Do NOT wrap the column in LOWER()/UPPER(), and do NOT invent a different
  spelling (not 'Ti-6Al-4V', not '%turning%').
- For a greeting, small talk, or anything NOT answerable from these tables,
  reply with a single table-free SELECT of a friendly message (shown verbatim to
  the user), e.g.:
    SELECT 'I can answer questions about your lab data — samples, materials, manufacturing operations, tests and tooling. What would you like to know?' AS note;
"""


def build_system_prompt() -> str:
    """Assemble the system prompt from the live database dictionary.

    Includes every documented object except the ones the guard denies (Directus
    system/credential/auth tables), with the curated ``v_*`` views listed first.
    """
    rows = db.fetch_dictionary_all()

    objects: dict[str, dict] = {}
    for row in rows:
        name = row["object_name"]
        # Keep the prompt lab-focused: skip guard-denied relations and all
        # Directus metadata tables (still guard-readable, just noisy in-prompt).
        if sql_guard.is_denied_relation(name) or name.lower().startswith("directus_"):
            continue
        obj = objects.setdefault(
            name, {"comment": row.get("object_comment"), "columns": []}
        )
        obj["columns"].append(row)

    # Views first (v_*), then base tables, each alphabetical — a stable order the
    # model can rely on.
    order = sorted(objects, key=lambda n: (not n.startswith("v_"), n))

    lines = [_SYSTEM_PREAMBLE, "Available tables and views:\n"]
    for name in order:
        obj = objects[name]
        lines.append(f"### {name}")
        desc = (obj["comment"] or "").strip()
        if desc:
            lines.append(desc)
        for col in obj["columns"]:
            comment = (col["column_comment"] or "").strip()
            suffix = f"  -- {comment}" if comment else ""
            lines.append(f"  {col['column_name']} {col['data_type']}{suffix}")
        lines.append("")

    return "\n".join(lines) + _known_values_section(objects)
