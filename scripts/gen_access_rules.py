#!/usr/bin/env python3
"""Generate the Lab Member permission rows from scripts/access_rules.json (ADR-0011).

access_rules.json is the single source of the row-level visibility rules. This script turns it into
`directus_permissions` rows and keeps the two places that carry them in step:

  --json     print every Lab Member row as JSON (tests compare the database with this)
  --sql      print the INSERT statement, between its BEGIN/END GENERATED markers
  --values   print only the filtered rows as `(collection, action, filter)` VALUES lines, to paste
             into the migration that applies a rule change (a migration is a snapshot, so it embeds
             the rules as they were on the day it was written)
  --write    replace the marked block in scripts/configure_users_and_policies.sql
  --check    exit 1 when that block differs from what the rules generate (CI runs this)

A rule is an OR of paths. Each path ends at a user column that must equal `$CURRENT_USER`, e.g.
`co_owners._some.user_id` becomes `{"co_owners": {"_some": {"user_id": {"_eq": "$CURRENT_USER"}}}}`.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES_FILE = HERE / "access_rules.json"
SCRIPT_FILE = HERE / "configure_users_and_policies.sql"

BEGIN = (
    "-- BEGIN GENERATED: Lab Member permissions "
    "(scripts/gen_access_rules.py --write; do not edit by hand)"
)
END = "-- END GENERATED: Lab Member permissions"
ACTIONS = ("create", "read", "update", "delete")
CURRENT_USER = "$CURRENT_USER"


class RulesError(ValueError):
    """The rules file is inconsistent."""


def load(path: Path = RULES_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expand(sets: dict, name: str, prefix: str = "", _stack: tuple = ()) -> list[str]:
    """All paths of a named set, with `prefix` put in front of each, in order."""
    if name not in sets:
        raise RulesError(f"unknown set {name!r}")
    if name in _stack:
        raise RulesError(
            f"set {name!r} includes itself ({' -> '.join(_stack + (name,))})"
        )
    out: list[str] = []
    for item in sets[name]:
        if isinstance(item, str):
            out.append(prefix + item)
        else:
            via = item.get("via", "")
            inner = f"{prefix}{via}." if via else prefix
            out.extend(expand(sets, item["set"], inner, _stack + (name,)))
    return out


def path_filter(path: str) -> dict:
    """`a.b._some.c` -> {"a": {"b": {"_some": {"c": {"_eq": "$CURRENT_USER"}}}}}."""
    node: dict = {"_eq": CURRENT_USER}
    for key in reversed(path.split(".")):
        node = {key: node}
    return node


def set_filter(sets: dict, name: str) -> dict:
    paths = list(dict.fromkeys(expand(sets, name)))  # drop duplicates, keep order
    filters = [path_filter(p) for p in paths]
    return filters[0] if len(filters) == 1 else {"_or": filters}


def build_rows(doc: dict) -> list[dict]:
    """Every Lab Member row: filtered collections first, then the unfiltered grants."""
    sets, policy = doc["sets"], doc["policy"]
    rows: list[dict] = []

    def row(collection: str, action: str, permissions: dict) -> dict:
        return {
            "collection": collection,
            "action": action,
            "permissions": permissions,
            "validation": {},
            "fields": "*",
            "policy": policy,
        }

    for collection, actions in doc["rules"].items():
        unknown = set(actions) - set(ACTIONS)
        if unknown:
            raise RulesError(f"{collection}: unknown action(s) {sorted(unknown)}")
        for action in ACTIONS:
            if action not in actions:
                continue
            rule = actions[action]
            if rule == "any":
                rows.append(row(collection, action, {}))
            elif action == "create":
                raise RulesError(
                    f'{collection}.create: Directus ignores item filters on create; use "any"'
                )
            else:
                rows.append(row(collection, action, set_filter(sets, rule)))
    seen = {(r["collection"], r["action"]) for r in rows}
    for collection, actions in doc["unfiltered"].items():
        for action in actions:
            if action not in ACTIONS:
                raise RulesError(f"{collection}: unknown action {action!r}")
            if (collection, action) in seen:
                raise RulesError(f"{collection}.{action} is both ruled and unfiltered")
            rows.append(row(collection, action, {}))
    return rows


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def sql_block(rows: list[dict]) -> str:
    lines = [
        BEGIN,
        "INSERT INTO directus_permissions (collection, action, permissions, validation, fields, policy) VALUES",
    ]
    values = [
        f"('{r['collection']}', '{r['action']}', '{compact(r['permissions'])}', "
        f"'{compact(r['validation'])}', '{r['fields']}', '{r['policy']}')"
        for r in rows
    ]
    lines.append(",\n".join(values) + ";")
    lines.append(END)
    return "\n".join(lines)


def migration_values(rows: list[dict], ruled: set[str]) -> str:
    """Every row of a collection that has rules (create rows included), as VALUES lines."""
    return ",\n".join(
        f"    ('{r['collection']}', '{r['action']}', '{compact(r['permissions'])}')"
        for r in rows
        if r["collection"] in ruled
    )


def script_block(script_text: str) -> tuple[int, int]:
    start = script_text.find(BEGIN)
    end = script_text.find(END)
    if start < 0 or end < 0 or end < start:
        raise RulesError(f"the script has no '{BEGIN[:40]}...' block")
    return start, end + len(END)


def render_script(script_text: str, rows: list[dict]) -> str:
    start, end = script_block(script_text)
    return script_text[:start] + sql_block(rows) + script_text[end:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    for flag in ("json", "sql", "values", "write", "check"):
        mode.add_argument(f"--{flag}", action="store_true")
    ap.add_argument("--rules", type=Path, default=RULES_FILE)
    ap.add_argument("--script", type=Path, default=SCRIPT_FILE)
    args = ap.parse_args(argv)

    doc = load(args.rules)
    try:
        rows = build_rows(doc)
    except RulesError as exc:
        print(f"access_rules: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(rows, indent=1))
    elif args.sql:
        print(sql_block(rows))
    elif args.values:
        print(migration_values(rows, set(doc["rules"])))
    elif args.write:
        text = args.script.read_text(encoding="utf-8")
        args.script.write_text(render_script(text, rows), encoding="utf-8")
    else:
        text = args.script.read_text(encoding="utf-8")
        if render_script(text, rows) != text:
            print(
                f"{args.script.name} differs from {args.rules.name}: "
                "run `python3 scripts/gen_access_rules.py --write`",
                file=sys.stderr,
            )
            return 1
        print(f"{args.script.name} matches {args.rules.name} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
