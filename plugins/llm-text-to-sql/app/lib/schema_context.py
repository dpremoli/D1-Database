"""Builds the compact schema prompt the LLM sees.

Spec §6 calls for a "semantic schema dictionary" and a "views abstraction
layer" so a context-window-limited local LLM can synthesise correct SQL. We
assemble that prompt straight from the database (v_llm_query_targets +
v_schema_dictionary), so the prompt always reflects the live schema and its
COMMENTs — there is no second copy to drift.
"""

from app.lib import db
from app.lib.sql_guard import ALLOWED_RELATIONS

_SYSTEM_PREAMBLE = """\
You are a careful PostgreSQL analyst for a materials-science laboratory database.
Translate the user's question into ONE read-only SQL SELECT statement.

Hard rules:
- Output ONLY the SQL. No prose, no explanation, no markdown fences.
- SELECT queries only. Never INSERT, UPDATE, DELETE, or any DDL.
- Query ONLY the views listed below. Do not reference any other table.
- Column names already carry their units (e.g. mass_grams, temperature_celsius).
- If the question cannot be answered from these views, return exactly:
    SELECT 'cannot answer from available views' AS note;
"""


def build_system_prompt() -> str:
    """Assemble the system prompt from the live database dictionary."""
    targets = db.fetch_query_targets()
    target_names = [
        t["view_name"] for t in targets if t["view_name"] in ALLOWED_RELATIONS
    ]
    dictionary = db.fetch_dictionary(target_names)

    columns_by_view: dict[str, list[dict]] = {}
    for row in dictionary:
        columns_by_view.setdefault(row["object_name"], []).append(row)

    lines = [_SYSTEM_PREAMBLE, "Available views:\n"]
    descriptions = {t["view_name"]: t["description"] for t in targets}
    for view in target_names:
        desc = (descriptions.get(view) or "").strip()
        lines.append(f"### {view}")
        if desc:
            lines.append(desc)
        for col in columns_by_view.get(view, []):
            comment = (col["column_comment"] or "").strip()
            suffix = f"  -- {comment}" if comment else ""
            lines.append(f"  {col['column_name']} {col['data_type']}{suffix}")
        lines.append("")

    return "\n".join(lines)
