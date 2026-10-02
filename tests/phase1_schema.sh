#!/usr/bin/env bash
# Phase 1 schema test: verifies migrations apply, views exist, triggers fire,
# seed data loads, and code-generation functions return correct output.
# Requires a running Postgres with DATABASE_URL set, or a local stack via `make up`.
#
# Usage:  DATABASE_URL=postgres://d1:secret@localhost:5432/d1_test bash tests/phase1_schema.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

: "${DATABASE_URL:?DATABASE_URL must be set (e.g. postgres://d1:pw@localhost:5432/d1_db)}"
PSQL="psql $DATABASE_URL --no-psqlrc -t -A"

pass=0; fail=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
run() {
    # run "label" "SQL"  — expects non-empty result from SQL
    local label="$1" sql="$2"
    local result
    result=$($PSQL -c "$sql" 2>&1) || { bad "$label (psql error: $result)"; return; }
    [[ -n "$result" ]] && ok "$label" || bad "$label (empty result)"
}
run_eq() {
    # run_eq "label" "SQL" "expected"
    local label="$1" sql="$2" expected="$3"
    local result
    result=$($PSQL -c "$sql" 2>&1) || { bad "$label (psql error: $result)"; return; }
    [[ "$result" == "$expected" ]] && ok "$label" || bad "$label (got '$result', want '$expected')"
}

echo "== Core tables exist =="
for tbl in \
    alloying_elements material_iso_classifications materials \
    manufacturing_methods equipment tools insert_types \
    projects raw_stock_lots \
    tool_boxes cutting_inserts insert_edges \
    physical_samples sample_genealogy sample_stock_provenance \
    manufacturing_operations test_sessions audit_logs
do
    run "$tbl exists" \
        "SELECT to_regclass('public.$tbl')::TEXT"
done

echo "== Views exist =="
for view in \
    v_complete_sample_history v_tooling_hierarchy v_sample_genealogy_flat \
    v_manufacturing_operations_full v_stock_provenance v_test_sessions_full \
    v_project_rollup
do
    run "$view exists" \
        "SELECT to_regclass('public.$view')::TEXT"
done

echo "== Extensions loaded =="
run "uuid-ossp"  "SELECT extname FROM pg_extension WHERE extname = 'uuid-ossp'"
run "vector"     "SELECT extname FROM pg_extension WHERE extname = 'vector'"
run "pg_trgm"    "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"

echo "== Seed data present =="
run "ISO groups seeded" \
    "SELECT iso_code FROM material_iso_classifications WHERE iso_code = 'S'"
run "Ti-6Al-4V seeded" \
    "SELECT alloy_code FROM materials WHERE alloy_code = 'AA'"
run "FAST method seeded" \
    "SELECT method_code FROM manufacturing_methods WHERE method_code = 'MF'"
run "Equipment seeded" \
    "SELECT equipment_code FROM equipment WHERE equipment_code = 'NLX-2500'"
echo "== Code-generation functions =="
run_eq "generate_sample_code" \
    "SELECT generate_sample_code(10, 'AA', 'MF', '2023-06-03'::DATE)" \
    "10-AA-MF-2023-06-03"

run_eq "generate_pass_code" \
    "SELECT generate_pass_code('9-AA-MR-2023-03-23', 'F', 9)" \
    "9-AA-MR-2023-03-23-F9"

run_eq "generate_force_file_id" \
    "SELECT generate_force_file_id('9-AA-MR-2023-03-23-F9', 20, 0.05, 0.1)" \
    "9-AA-MR-2023-03-23-F9-20MPM_0.05feed_0.1DoC"

echo "== Directus group-detail accordions are renderable =="
# Regression guard for the "Unexpected Error" (TypeError: ...reading 'map') that the
# interface-group-detail throws at render time when a group field lacks the 'group'
# special. Directus needs special to include 'group' (alongside alias,no-data) to
# resolve the group's child fields; without it the accordion crashes when shown.
# This affected EVERY accordion on manufacturing_operations and test_sessions.
run_eq "every group-detail field carries the 'group' special" \
    "SELECT count(*) FROM directus_fields
     WHERE interface = 'group-detail'
       AND (special IS NULL OR special NOT LIKE '%group%')" \
    "0"

echo "== Sample geometry: round bar form migration =="
# CI has no Directus bootstrap rows (directus_fields is an empty stub), so seed the pre-migration
# state, apply the migration's up then down SQL, and assert both — all in a rolled-back transaction.
MIG=db/migrations/20260930000114_round_bar_form.sql
mig_up=$(awk '/-- migrate:up/{f=1;next}/-- migrate:down/{f=0}f' "$MIG")
mig_down=$(awk '/-- migrate:down/{f=1;next}f' "$MIG")
rb_out=$($PSQL 2>&1 <<SQL
BEGIN;
DELETE FROM directus_fields WHERE collection='physical_samples' AND field IN ('form','diameter_mm','length_mm');
INSERT INTO directus_fields (collection, field, options, conditions) VALUES
  ('physical_samples','form','{"choices":[]}',NULL),
  ('physical_samples','diameter_mm',NULL,'[]'),
  ('physical_samples','length_mm',NULL,'[]');
INSERT INTO physical_samples (sample_code, form) VALUES ('TEST-RB-001','round_bar');
$mig_up
SELECT 'up_form_choice:' || count(*) FROM directus_fields
  WHERE field='form' AND options::text LIKE '%"round_bar"%';
SELECT 'up_dim_fields:' || count(*) FROM directus_fields
  WHERE field IN ('diameter_mm','length_mm') AND conditions::text LIKE '%"round_bar"%';
$mig_down
SELECT 'down_fields:' || count(*) FROM directus_fields
  WHERE collection='physical_samples' AND (options::text LIKE '%round_bar%' OR conditions::text LIKE '%round_bar%');
SELECT 'down_form:' || form FROM physical_samples WHERE sample_code='TEST-RB-001';
ROLLBACK;
SQL
)
rb_check() { grep -qx "$1" <<<"$rb_out" && ok "$2" || bad "$2 (psql output: $rb_out)"; }
rb_check "up_form_choice:1" "up: Geometry dropdown offers round_bar"
rb_check "up_dim_fields:2" "up: diameter_mm and length_mm are shown for round_bar"
rb_check "down_fields:0" "down: round_bar removed from dropdown and conditions"
rb_check "down_form:cylinder" "down: round_bar samples are mapped to cylinder"

echo "== Sample geometry: legacy forms are back-filled =="
# Seed old-vocabulary samples, apply the back-fill's up SQL, assert, then ROLLBACK.
BACKFILL=db/migrations/20260930000115_backfill_legacy_geometry_forms.sql
bf_up=$(awk '/-- migrate:up/{f=1;next}/-- migrate:down/{f=0}f' "$BACKFILL")
bf_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO physical_samples (sample_code, form) VALUES
  ('TEST-LG-001','cylindrical'), ('TEST-LG-002','Rectangular'), ('TEST-LG-003','disc'), ('TEST-LG-004','round_bar');
$bf_up
SELECT 'lg:' || sample_code || '=' || form FROM physical_samples WHERE sample_code LIKE 'TEST-LG-%' ORDER BY sample_code;
ROLLBACK;
SQL
)
bf_check() { grep -qx "$1" <<<"$bf_out" && ok "$2" || bad "$2 (psql output: $bf_out)"; }
bf_check "lg:TEST-LG-001=cylinder" "cylindrical -> cylinder"
bf_check "lg:TEST-LG-002=block" "Rectangular -> block (case-insensitive)"
bf_check "lg:TEST-LG-003=disc" "current values are left alone (disc)"
bf_check "lg:TEST-LG-004=round_bar" "current values are left alone (round_bar)"

echo "== Natural ordering of ID codes (#115) =="
# The code columns use the ICU numeric collation natural_sort, so ORDER BY (and a Directus
# column-header sort) puts 9 < 10 < 151 < 1000 and ...-F9 < ...-F10. Test rows live in a
# rolled-back transaction; the migration's down + up are replayed in it too.
NAT=db/migrations/20261002000116_natural_code_collation.sql
nat_up=$(awk '/-- migrate:up/{f=1;next}/-- migrate:down/{f=0}f' "$NAT")
nat_down=$(awk '/-- migrate:down/{f=1;next}f' "$NAT")
run_eq "natural_sort is an ICU collation" \
    "SELECT count(*) FROM pg_collation WHERE collname = 'natural_sort' AND collprovider = 'i'" \
    "1"
run_eq "the 8 code columns use natural_sort" \
    "SELECT count(*) FROM information_schema.columns
     WHERE table_schema = 'public' AND collation_name = 'natural_sort'
       AND (table_name, column_name) IN (
           ('physical_samples','sample_code'), ('manufacturing_operations','pass_code'),
           ('tools','tool_code'), ('cutting_inserts','insert_code'),
           ('tool_boxes','tool_box_code'), ('insert_edges','edge_code'),
           ('raw_stock_lots','lot_code'), ('projects','project_code'))" \
    "8"
run_eq "code_sort is still generated, in the default collation" \
    "SELECT count(*) FROM information_schema.columns
     WHERE table_schema = 'public' AND column_name = 'code_sort' AND is_generated = 'ALWAYS'
       AND collation_name IS NULL AND table_name IN ('physical_samples','manufacturing_operations')" \
    "2"
run_eq "recreated views keep the text-to-SQL read grant" \
    "SELECT count(*) FROM unnest(ARRAY['v_project_rollup','v_complete_sample_history',
        'v_manufacturing_operations_full','v_sample_genealogy_flat','v_stock_provenance',
        'v_test_sessions_full','v_tooling_hierarchy']) AS v(name)
     WHERE has_table_privilege('d1_llm_readonly', v.name, 'SELECT')
       AND obj_description(v.name::regclass, 'pg_class') IS NOT NULL" \
    "7"
nat_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO physical_samples (sample_code) VALUES
  ('1000-TESTNAT-MF-2026-10-1'), ('151-TESTNAT-MF-2026-10-1'), ('99-TESTNAT-MF-2026-10-1'),
  ('10-TESTNAT-MF-2026-10-1'), ('9-TESTNAT-MF-2026-10-1'),
  ('9-TESTNAT-MR-2023-03-23-F10'), ('9-TESTNAT-MR-2023-03-23-F9');
SELECT 'order:' || string_agg(split_part(sample_code, '-', 1), '<' ORDER BY sample_code)
  FROM physical_samples WHERE sample_code LIKE '%-TESTNAT-MF-%';
SELECT 'suffix:' || string_agg(substring(sample_code FROM 'F[0-9]+$'), '<' ORDER BY sample_code)
  FROM physical_samples WHERE sample_code LIKE '%-TESTNAT-MR-%';
SELECT 'view:' || string_agg(split_part(sample_code, '-', 1), '<' ORDER BY sample_code)
  FROM v_complete_sample_history WHERE sample_code LIKE '%-TESTNAT-MF-%';
SELECT 'code_sort:' || code_sort FROM physical_samples WHERE sample_code = '9-TESTNAT-MF-2026-10-1';
SELECT 'unique:' || count(*) FROM physical_samples WHERE sample_code = '10-TESTNAT-MF-2026-10-1';
$nat_down
SELECT 'down_columns:' || count(*) FROM information_schema.columns
  WHERE table_schema = 'public' AND collation_name = 'natural_sort';
SELECT 'down_collation:' || count(*) FROM pg_collation WHERE collname = 'natural_sort';
$nat_up
SELECT 'reup_order:' || string_agg(split_part(sample_code, '-', 1), '<' ORDER BY sample_code)
  FROM physical_samples WHERE sample_code LIKE '%-TESTNAT-MF-%';
SELECT 'reup_views:' || count(*) FROM pg_views
  WHERE schemaname = 'public' AND viewname IN ('v_project_rollup','v_complete_sample_history',
    'v_manufacturing_operations_full','v_sample_genealogy_flat','v_stock_provenance',
    'v_test_sessions_full','v_tooling_hierarchy');
ROLLBACK;
SQL
)
nat_check() { grep -qx "$1" <<<"$nat_out" && ok "$2" || bad "$2 (psql output: $nat_out)"; }
nat_check "order:9<10<99<151<1000" "sample_code sorts by number: 9 < 10 < 99 < 151 < 1000"
nat_check "suffix:F9<F10" "later digit runs too: ...-F9 < ...-F10"
nat_check "view:9<10<99<151<1000" "views inherit the ordering (v_complete_sample_history)"
nat_check "code_sort:00000009-TESTNAT-MF-2026-10-1" "code_sort keeps its zero-padded value"
nat_check "unique:1" "equality is unchanged"
nat_check "down_columns:0" "down: code columns back on the default collation"
nat_check "down_collation:0" "down: collation dropped"
nat_check "reup_order:9<10<99<151<1000" "up again: natural ordering restored"
nat_check "reup_views:7" "up again: all 7 dependent views recreated"

echo "== Campaigns layer (trials + testing campaigns) =="
run "campaigns table exists" \
    "SELECT to_regclass('public.campaigns')::TEXT"
run "manufacturing_operations.campaign_id column exists" \
    "SELECT column_name FROM information_schema.columns
     WHERE table_name='manufacturing_operations' AND column_name='campaign_id'"
run "test_sessions.campaign_id column exists" \
    "SELECT column_name FROM information_schema.columns
     WHERE table_name='test_sessions' AND column_name='campaign_id'"
run_eq "campaign_type CHECK restricts to the two kinds" \
    "SELECT count(*) FROM information_schema.check_constraints
     WHERE constraint_name LIKE '%campaign_type%'
       AND check_clause LIKE '%machining_trial%'
       AND check_clause LIKE '%testing_campaign%'" \
    "1"
run_eq "Directus relations for campaigns are registered (2)" \
    "SELECT count(*) FROM directus_relations
     WHERE one_collection='campaigns' OR many_collection='campaigns'
        OR (many_collection IN ('manufacturing_operations','test_sessions') AND many_field='campaign_id')" \
    "2"

echo "== Audit trigger fires on INSERT =="
# Insert a test sample and verify audit_logs captured it.
$PSQL -c "
    INSERT INTO physical_samples (sample_code, current_status)
    VALUES ('TEST-AUDIT-001', 'active');
" > /dev/null 2>&1 || true
run "audit INSERT recorded" \
    "SELECT table_name FROM audit_logs
     WHERE table_name = 'physical_samples'
       AND action_type = 'INSERT'
       AND row_after->>'sample_code' = 'TEST-AUDIT-001'"

echo "== OCC trigger increments version on UPDATE =="
$PSQL -c "
    UPDATE physical_samples SET notes = 'occ-test' WHERE sample_code = 'TEST-AUDIT-001';
" > /dev/null 2>&1 || true
run_eq "OCC version = 2 after UPDATE" \
    "SELECT version FROM physical_samples WHERE sample_code = 'TEST-AUDIT-001'" \
    "2"

echo "== Audit immutability (NO UPDATE rule) =="
$PSQL -c "UPDATE audit_logs SET table_name = 'hacked' WHERE log_id = 1;" > /dev/null 2>&1 || true
run "audit_logs UPDATE is silently blocked" \
    "SELECT COUNT(*) FROM audit_logs WHERE table_name = 'hacked'" 2>/dev/null
# The rule makes UPDATE a no-op; table_name 'hacked' should not exist.

echo "== Self-referential genealogy =="
$PSQL -c "
    INSERT INTO physical_samples (sample_code, current_status)
    VALUES ('TEST-PARENT-001', 'consumed'),
           ('TEST-CHILD-001', 'active');
    INSERT INTO sample_genealogy (child_sample_id, parent_sample_id, relationship_type)
    SELECT c.sample_id, p.sample_id, 'cut_from'
    FROM physical_samples AS c, physical_samples AS p
    WHERE c.sample_code = 'TEST-CHILD-001'
      AND p.sample_code = 'TEST-PARENT-001';
" > /dev/null 2>&1 || true
run "genealogy insert roundtrips via view" \
    "SELECT child_sample_code FROM v_sample_genealogy_flat
     WHERE parent_sample_code = 'TEST-PARENT-001'"

echo "== Cleanup test rows =="
$PSQL -c "
    DELETE FROM sample_genealogy
    WHERE child_sample_id IN (
        SELECT sample_id FROM physical_samples
        WHERE sample_code IN ('TEST-AUDIT-001','TEST-CHILD-001','TEST-PARENT-001')
    );
    DELETE FROM physical_samples
    WHERE sample_code IN ('TEST-AUDIT-001','TEST-CHILD-001','TEST-PARENT-001');
" > /dev/null 2>&1 || true
ok "test rows cleaned up"

echo
echo "Results: $pass passed, $fail failed"
[[ $fail -eq 0 ]] || exit 1
echo "Phase 1 schema OK."
