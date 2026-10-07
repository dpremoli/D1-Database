"""ADR-0011 row-level visibility: scripts/access_rules.json, its generator and the script block.

Pure checks run everywhere. The path check needs a migrated Postgres (DATABASE_URL and psql) to
prove that every column a rule names exists; it skips otherwise (the CI job sets
REQUIRE_DB_TESTS=1, so a skip there fails the job).
"""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location(
    "gen_access_rules", SCRIPTS / "gen_access_rules.py"
)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

DOC = gen.load()
ROWS = gen.build_rows(DOC)
BY_KEY = {(r["collection"], r["action"]): r for r in ROWS}

# Reference data every member can read and edit, as before ADR-0011.
REFERENCE = [
    "materials", "material_iso_classifications", "alloying_elements", "material_alloying_elements",
    "equipment", "tools", "tool_boxes", "cutting_inserts", "insert_edges", "insert_types",
    "raw_stock_lots", "manufacturing_methods", "people", "facilities", "fast_recipes",
]  # fmt: skip

# Relation fields a rule may traverse -> the collection they lead to. Aliases (O2M / M2M fields)
# lead to their junction or child collection. Mirrors scripts/configure_directus.sql and the
# *_directus_meta migrations; a path that leaves this map fails the test.
REL = {
    ("physical_samples", "owner_person_id"): "people",
    ("physical_samples", "project_id"): "projects",
    ("physical_samples", "co_owners"): "sample_co_owners",
    ("physical_samples", "campaigns"): "campaign_samples",
    ("campaign_samples", "campaign_id"): "campaigns",
    ("campaign_samples", "sample_id"): "physical_samples",
    ("campaigns", "owner_person_id"): "people",
    ("campaigns", "project_id"): "projects",
    ("campaigns", "samples"): "campaign_samples",
    ("projects", "principal_investigator_person"): "people",
    ("projects", "secondary_investigators"): "project_investigators",
    ("projects", "campaigns"): "campaigns",
    ("projects", "samples"): "physical_samples",
    ("project_investigators", "project_id"): "projects",
    ("manufacturing_operations", "owner_person_id"): "people",
    ("manufacturing_operations", "sample_id"): "physical_samples",
    ("manufacturing_operations", "project_id"): "projects",
    ("manufacturing_operations", "campaign_id"): "campaigns",
    ("test_sessions", "owner_person_id"): "people",
    ("test_sessions", "sample_id"): "physical_samples",
    ("test_sessions", "project_id"): "projects",
    ("test_sessions", "campaign_id"): "campaigns",
    ("sample_co_owners", "sample_id"): "physical_samples",
    ("sample_stock_provenance", "sample_id"): "physical_samples",
    ("sample_data_files", "sample_id"): "physical_samples",
    ("sample_genealogy", "child_sample_id"): "physical_samples",
    ("sample_genealogy", "parent_sample_id"): "physical_samples",
    ("operation_data_files", "operation_id"): "manufacturing_operations",
    ("machining_force_analysis", "operation_id"): "manufacturing_operations",
    ("fast_run_data", "operation_id"): "manufacturing_operations",
    ("session_data_files", "session_id"): "test_sessions",
    ("test_sessions_subject", "test_sessions_id"): "test_sessions",
    ("project_rollup", "project_id"): "projects",
}
# The columns a path may end at, per table: the login the user is matched against.
USER_COLUMNS = {
    ("people", "user_id"),
    ("sample_co_owners", "user_id"),
    ("project_investigators", "user_id"),
}
# Alias fields have no database column.
ALIASES = {
    ("physical_samples", "co_owners"),
    ("physical_samples", "campaigns"),
    ("campaigns", "samples"),
    ("projects", "secondary_investigators"),
    ("projects", "campaigns"),
    ("projects", "samples"),
}


def _paths(collection, action):
    return list(
        dict.fromkeys(gen.expand(DOC["sets"], DOC["rules"][collection][action]))
    )


def _rule_paths():
    for collection, actions in DOC["rules"].items():
        for action, rule in actions.items():
            if rule != "any":
                yield collection, action, _paths(collection, action)


def _walk(collection, path):
    """Follow a path from `collection`; return [(table, column), ...] to check in the database."""
    table, columns = collection, []
    parts = [p for p in path.split(".") if p != "_some"]
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if last:
            assert (
                table,
                part,
            ) in USER_COLUMNS, f"{collection}: {path} ends at {table}.{part}"
            columns.append((table, part))
        else:
            assert (
                table,
                part,
            ) in REL, f"{collection}: {path}: {table}.{part} is not a known relation"
            if (table, part) not in ALIASES:
                columns.append((table, part))
            table = REL[(table, part)]
    return columns


def test_generated_script_block_is_current():
    script = SCRIPTS / "configure_users_and_policies.sql"
    assert gen.render_script(
        script.read_text(encoding="utf-8"), ROWS
    ) == script.read_text(
        encoding="utf-8"
    ), "run `python3 scripts/gen_access_rules.py --write`"


def test_check_command_detects_a_hand_edit(tmp_path):
    script = tmp_path / "configure_users_and_policies.sql"
    text = (SCRIPTS / "configure_users_and_policies.sql").read_text(encoding="utf-8")
    script.write_text(text.replace('"_or"', '"_and"', 1), encoding="utf-8")
    assert gen.main(["--check", "--script", str(script)]) == 1
    script.write_text(text, encoding="utf-8")
    assert gen.main(["--check", "--script", str(script)]) == 0


def test_script_has_no_ungenerated_lab_member_rows():
    """The only INSERT INTO directus_permissions in the script is the generated one."""
    text = (SCRIPTS / "configure_users_and_policies.sql").read_text(encoding="utf-8")
    assert text.count("INSERT INTO directus_permissions") == 1
    start, end = gen.script_block(text)
    assert "INSERT INTO directus_permissions" in text[start:end]


def test_create_is_never_filtered():
    for (collection, action), row in BY_KEY.items():
        if action == "create":
            assert row["permissions"] == {}, collection


def test_reference_data_stays_unfiltered():
    for collection in REFERENCE:
        rows = [r for (c, _a), r in BY_KEY.items() if c == collection]
        assert rows, f"{collection} lost its Lab Member grant"
        assert all(r["permissions"] == {} for r in rows), collection
        assert collection not in DOC["rules"]


def test_previously_granted_actions_are_kept():
    """Every (collection, action) the old hand-written script and later migrations granted."""
    granted = {
        ("physical_samples", a) for a in gen.ACTIONS
    } | {
        ("manufacturing_operations", a) for a in gen.ACTIONS
    } | {("test_sessions", a) for a in gen.ACTIONS} | {("projects", a) for a in gen.ACTIONS} | {
        ("machining_force_analysis", a) for a in ("create", "read", "update")
    } | {("fast_run_data", "read"), ("directus_files", "create"), ("directus_files", "read"),
         ("audit_logs", "read")}  # fmt: skip
    assert granted <= set(BY_KEY)


def test_directus_files_and_audit_logs_are_untouched():
    for key in [
        ("directus_files", "read"),
        ("directus_files", "create"),
        ("audit_logs", "read"),
    ]:
        assert BY_KEY[key]["permissions"] == {}


def test_every_leaf_matches_the_signed_in_user():
    def leaves(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "_eq":
                    yield value
                else:
                    yield from leaves(value)
        elif isinstance(node, list):
            for item in node:
                yield from leaves(item)

    for row in ROWS:
        assert set(leaves(row["permissions"])) <= {"$CURRENT_USER"}, row["collection"]


def test_update_and_delete_are_narrower_than_read():
    """Owner decision 4: PI and investigator access through a project is read-only."""
    for collection in (
        "physical_samples",
        "manufacturing_operations",
        "test_sessions",
        "campaigns",
    ):
        for action in ("update", "delete"):
            text = json.dumps(BY_KEY[(collection, action)]["permissions"])
            assert "principal_investigator_person" not in text, (collection, action)
            assert "secondary_investigators" not in text, (collection, action)
    assert "co_owners" not in json.dumps(
        BY_KEY[("physical_samples", "delete")]["permissions"]
    )
    assert "co_owners" in json.dumps(
        BY_KEY[("physical_samples", "update")]["permissions"]
    )
    # operations and tests: the owner of the record, or an owner / co-owner of the sample
    update = json.dumps(BY_KEY[("manufacturing_operations", "update")]["permissions"])
    assert "sample_id" in update and "co_owners" in update
    delete = BY_KEY[("manufacturing_operations", "delete")]["permissions"]
    assert delete == {"owner_person_id": {"user_id": {"_eq": "$CURRENT_USER"}}}
    # projects: the PI alone
    pi = {"principal_investigator_person": {"user_id": {"_eq": "$CURRENT_USER"}}}
    assert BY_KEY[("projects", "update")]["permissions"] == pi
    assert BY_KEY[("projects", "delete")]["permissions"] == pi


def test_project_rollup_is_for_pi_and_investigators_only():
    paths = _paths("project_rollup", "read")
    assert paths == [
        "project_id.principal_investigator_person.user_id",
        "project_id.secondary_investigators._some.user_id",
    ]


def test_set_cycles_and_unknown_sets_are_rejected():
    with pytest.raises(gen.RulesError):
        gen.expand({"a": [{"set": "a"}]}, "a")
    with pytest.raises(gen.RulesError):
        gen.expand({"a": [{"set": "missing"}]}, "a")
    with pytest.raises(gen.RulesError):
        gen.build_rows(
            {**DOC, "rules": {"physical_samples": {"create": "sample.read"}}}
        )


def test_path_filter_shape():
    assert gen.path_filter("co_owners._some.user_id") == {
        "co_owners": {"_some": {"user_id": {"_eq": "$CURRENT_USER"}}}
    }


@pytest.mark.parametrize("collection,action,paths", list(_rule_paths()))
def test_every_path_follows_known_relations(collection, action, paths):
    for path in paths:
        _walk(collection, path)


def _psql(sql):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn or shutil.which("psql") is None:
        pytest.skip("needs DATABASE_URL and psql")
    r = subprocess.run(
        ["psql", dsn, "--no-psqlrc", "-Atc", sql], capture_output=True, text=True
    )
    if r.returncode != 0:
        pytest.skip(f"database unreachable: {r.stderr.strip()}")
    return r.stdout.strip()


def test_every_column_a_rule_names_exists():
    if _psql("SELECT to_regclass('public.physical_samples') IS NOT NULL") != "t":
        pytest.skip("database is not migrated")
    have = {
        tuple(line.split("."))
        for line in _psql(
            "SELECT table_name || '.' || column_name FROM information_schema.columns "
            "WHERE table_schema='public'"
        ).splitlines()
    }
    missing = []
    for collection, _action, paths in _rule_paths():
        for path in paths:
            for table, column in _walk(collection, path):
                if (table, column) not in have:
                    missing.append(f"{table}.{column} (rule {collection}: {path})")
    assert not missing, missing


def test_co_owners_is_not_a_real_column_any_more():
    """The permission filter's `co_owners` must be the M2M alias, not the legacy TEXT column."""
    if _psql("SELECT to_regclass('public.physical_samples') IS NOT NULL") != "t":
        pytest.skip("database is not migrated")
    assert (
        _psql(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='physical_samples' AND column_name='co_owners'"
        )
        == "0"
    )
