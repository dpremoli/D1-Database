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
# migration 129 back-fills process_category before the seed runs on a fresh install, so the seed carries it
run_eq "seeded methods carry the process_category migration 129 maps" \
    "SELECT string_agg(method_code || '=' || COALESCE(process_category, 'NULL'), ',' ORDER BY method_code)
       FROM manufacturing_methods WHERE method_code IN ('HT','MC','MF','MM','MO','MR')" \
    "HT=heat_treatment,MC=machining,MF=sintering,MM=machining,MO=deformation,MR=deformation"
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
run_eq "the 12 code columns use natural_sort" \
    "SELECT count(*) FROM information_schema.columns
     WHERE table_schema = 'public' AND collation_name = 'natural_sort'
       AND (table_name, column_name) IN (
           ('physical_samples','sample_code'), ('manufacturing_operations','pass_code'),
           ('tools','tool_code'), ('cutting_inserts','insert_code'),
           ('tool_boxes','tool_box_code'), ('insert_edges','edge_code'),
           ('raw_stock_lots','lot_code'), ('projects','project_code'),
           ('materials','alloy_code'), ('equipment','equipment_code'),
           ('campaigns','campaign_code'), ('project_rollup','code'))" \
    "12"
run_eq "v_project_rollup.code is natural_sort" \
    "SELECT c.collname FROM pg_attribute a JOIN pg_collation c ON c.oid = a.attcollation
     WHERE a.attrelid = 'v_project_rollup'::regclass AND a.attname = 'code'" \
    "natural_sort"
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
-- project rollup: the cache table Directus shows and the live view it is refreshed from
-- (the operations trigger refreshes project_rollup on insert)
INSERT INTO projects (project_code, project_name) VALUES ('ZZ-TESTNAT', 'natural rollup probe');
INSERT INTO physical_samples (sample_code) VALUES ('TESTNAT-ROLLUP-SAMPLE');
INSERT INTO manufacturing_operations (method_id, project_id, sample_id, pass_code)
SELECT (SELECT method_id FROM manufacturing_methods LIMIT 1),
       (SELECT project_id FROM projects WHERE project_code = 'ZZ-TESTNAT'),
       (SELECT sample_id FROM physical_samples WHERE sample_code = 'TESTNAT-ROLLUP-SAMPLE'),
       c
FROM unnest(ARRAY['1000-TESTNATRU-MF-1', '151-TESTNATRU-MF-1', '99-TESTNATRU-MF-1',
                  '10-TESTNATRU-MF-1', '9-TESTNATRU-MF-1',
                  '9-TESTNATRU-MR-F10', '9-TESTNATRU-MR-F9']) AS c;
SELECT 'rollup_table:' || string_agg(split_part(code, '-', 1), '<' ORDER BY code)
  FROM project_rollup WHERE kind = 'operation' AND code LIKE '%-TESTNATRU-MF-%';
SELECT 'rollup_table_suffix:' || string_agg(substring(code FROM 'F[0-9]+$'), '<' ORDER BY code)
  FROM project_rollup WHERE kind = 'operation' AND code LIKE '%-TESTNATRU-MR-%';
SELECT 'rollup_view:' || string_agg(split_part(code, '-', 1), '<' ORDER BY code)
  FROM v_project_rollup WHERE kind = 'operation' AND code LIKE '%-TESTNATRU-MF-%';
SELECT 'rollup_view_suffix:' || string_agg(substring(code FROM 'F[0-9]+$'), '<' ORDER BY code)
  FROM v_project_rollup WHERE kind = 'operation' AND code LIKE '%-TESTNATRU-MR-%';
SELECT 'unique:' || count(*) FROM physical_samples WHERE sample_code = '10-TESTNAT-MF-2026-10-1';
$nat_down
SELECT 'down_columns:' || count(*) FROM information_schema.columns
  WHERE table_schema = 'public' AND collation_name = 'natural_sort';
SELECT 'down_collation:' || count(*) FROM pg_collation WHERE collname = 'natural_sort';
SELECT 'down_rollup_collation:' || count(*) FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'project_rollup' AND column_name = 'code'
    AND collation_name IS NULL;
$nat_up
SELECT 'reup_order:' || string_agg(split_part(sample_code, '-', 1), '<' ORDER BY sample_code)
  FROM physical_samples WHERE sample_code LIKE '%-TESTNAT-MF-%';
SELECT 'reup_rollup_table:' || string_agg(split_part(code, '-', 1), '<' ORDER BY code)
  FROM project_rollup WHERE kind = 'operation' AND code LIKE '%-TESTNATRU-MF-%';
SELECT 'reup_rollup_view:' || string_agg(split_part(code, '-', 1), '<' ORDER BY code)
  FROM v_project_rollup WHERE kind = 'operation' AND code LIKE '%-TESTNATRU-MF-%';
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
nat_check "rollup_table:9<10<99<151<1000" "project_rollup (the Directus cache table) sorts by number: 9 < 10 < 99 < 151 < 1000"
nat_check "rollup_table_suffix:F9<F10" "project_rollup: ...-F9 < ...-F10"
nat_check "rollup_view:9<10<99<151<1000" "v_project_rollup sorts by number: 9 < 10 < 99 < 151 < 1000"
nat_check "rollup_view_suffix:F9<F10" "v_project_rollup: ...-F9 < ...-F10"
nat_check "down_columns:0" "down: code columns back on the default collation"
nat_check "down_collation:0" "down: collation dropped"
nat_check "reup_order:9<10<99<151<1000" "up again: natural ordering restored"
nat_check "down_rollup_collation:1" "down: project_rollup.code back on the default collation"
nat_check "reup_rollup_table:9<10<99<151<1000" "up again: project_rollup natural ordering restored"
nat_check "reup_rollup_view:9<10<99<151<1000" "up again: v_project_rollup natural ordering restored"
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

echo "== project_rollup refresh survives concurrent writers (review 5.1) =="
# Two sessions updating DIFFERENT operations used to fail the second with a duplicate key on
# project_rollup_pkey. Session A holds its transaction open (after its refresh has run); B must
# queue on the advisory lock and then succeed.
$PSQL -c "
    INSERT INTO manufacturing_methods (method_id, method_code, method_name)
    VALUES ('c0000000-0000-4000-8000-0000000000a1', 'T-C-RL', 'rollup lock test method');
    INSERT INTO projects (project_id, project_code, project_name)
    VALUES ('c0000000-0000-4000-8000-0000000000b1', 'TCRL-1', 'rollup lock test');
    INSERT INTO physical_samples (sample_id, sample_code)
    VALUES ('c0000000-0000-4000-8000-0000000000d0', 'TEST-RL-001');
    INSERT INTO manufacturing_operations (operation_id, method_id, project_id, sample_id, pass_code) VALUES
        ('c0000000-0000-4000-8000-0000000000c1', 'c0000000-0000-4000-8000-0000000000a1', 'c0000000-0000-4000-8000-0000000000b1', 'c0000000-0000-4000-8000-0000000000d0', 'TCRL-OP-1'),
        ('c0000000-0000-4000-8000-0000000000c2', 'c0000000-0000-4000-8000-0000000000a1', 'c0000000-0000-4000-8000-0000000000b1', 'c0000000-0000-4000-8000-0000000000d0', 'TCRL-OP-2');
" > /dev/null 2>&1 || true
rl_a_log=$(mktemp); rl_b_log=$(mktemp)
psql "$DATABASE_URL" --no-psqlrc -q -v ON_ERROR_STOP=1 > "$rl_a_log" 2>&1 <<SQL &
BEGIN;
UPDATE manufacturing_operations SET outcome_notes = 'rl-a' WHERE operation_id = 'c0000000-0000-4000-8000-0000000000c1';
SELECT pg_sleep(3);
COMMIT;
SQL
rl_a_pid=$!
sleep 1
rl_b_start=$(date +%s)
$PSQL -v ON_ERROR_STOP=1 -c "UPDATE manufacturing_operations SET outcome_notes = 'rl-b' WHERE operation_id = 'c0000000-0000-4000-8000-0000000000c2'" > "$rl_b_log" 2>&1
rl_b_rc=$?
rl_b_secs=$(( $(date +%s) - rl_b_start ))
wait "$rl_a_pid"; rl_a_rc=$?
[[ $rl_a_rc -eq 0 ]] && ok "session A (held open) committed" || bad "session A failed: $(cat "$rl_a_log")"
[[ $rl_b_rc -eq 0 ]] && ok "session B (different operation) succeeded" || bad "session B failed: $(cat "$rl_b_log")"
[[ $rl_b_secs -ge 1 ]] && ok "session B queued behind A's refresh (${rl_b_secs}s)" || bad "session B did not wait for A (${rl_b_secs}s): the refresh is not serialised"
run_eq "both concurrent updates landed" \
    "SELECT string_agg(outcome_notes, ',' ORDER BY pass_code) FROM manufacturing_operations WHERE pass_code IN ('TCRL-OP-1','TCRL-OP-2')" \
    "rl-a,rl-b"
run_eq "project_rollup cache equals v_project_rollup after the race" \
    "SELECT (SELECT count(*) FROM project_rollup) = (SELECT count(*) FROM v_project_rollup)" "t"
rm -f "$rl_a_log" "$rl_b_log"
$PSQL -c "
    DELETE FROM manufacturing_operations WHERE operation_id IN ('c0000000-0000-4000-8000-0000000000c1','c0000000-0000-4000-8000-0000000000c2');
    DELETE FROM physical_samples WHERE sample_id = 'c0000000-0000-4000-8000-0000000000d0';
    DELETE FROM projects WHERE project_id = 'c0000000-0000-4000-8000-0000000000b1';
    DELETE FROM manufacturing_methods WHERE method_id = 'c0000000-0000-4000-8000-0000000000a1';
" > /dev/null 2>&1 || true

echo "== Denormalised views keep every operation and test session (review 5.2) =="
# Row parity between each view and its base table, including an operation that only has
# output_sample_id and a test session whose subject is not a sample (test_sessions_subject).
vp_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_methods (method_id, method_code, method_name)
VALUES ('c0000000-0000-4000-8000-0000000000a2', 'T-C-VP', 'view parity test method');
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-0000000000d1', 'TEST-VP-001');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, pass_code) VALUES
    ('c0000000-0000-4000-8000-0000000000c3', 'c0000000-0000-4000-8000-0000000000a2', 'c0000000-0000-4000-8000-0000000000d1', 'TEST-VP-OP-IN');
INSERT INTO manufacturing_operations (operation_id, method_id, output_sample_id, pass_code) VALUES
    ('c0000000-0000-4000-8000-0000000000c4', 'c0000000-0000-4000-8000-0000000000a2', 'c0000000-0000-4000-8000-0000000000d1', 'TEST-VP-OP-OUT');
INSERT INTO test_sessions (session_id, sample_id) VALUES
    ('c0000000-0000-4000-8000-0000000000e1', 'c0000000-0000-4000-8000-0000000000d1');
INSERT INTO test_sessions (session_id) VALUES ('c0000000-0000-4000-8000-0000000000e2');
INSERT INTO test_sessions_subject (test_sessions_id, collection, item)
VALUES ('c0000000-0000-4000-8000-0000000000e2', 'tools', 'subject-only');
SELECT 'ops_parity:' || ((SELECT count(*) FROM v_manufacturing_operations_full) = (SELECT count(*) FROM manufacturing_operations));
SELECT 'ts_parity:' || ((SELECT count(*) FROM v_test_sessions_full) = (SELECT count(*) FROM test_sessions));
SELECT 'op_out_only_in_view:' || count(*) FROM v_manufacturing_operations_full WHERE pass_code = 'TEST-VP-OP-OUT' AND sample_id IS NULL;
SELECT 'ts_subject_only_in_view:' || count(*) FROM v_test_sessions_full WHERE session_id = 'c0000000-0000-4000-8000-0000000000e2' AND sample_code IS NULL;
SELECT 'ts_with_sample_code:' || sample_code FROM v_test_sessions_full WHERE session_id = 'c0000000-0000-4000-8000-0000000000e1';
ROLLBACK;
SQL
)
vp_check() { grep -qx "$1" <<<"$vp_out" && ok "$2" || bad "$2 (psql output: $vp_out)"; }
vp_check "ops_parity:true" "v_manufacturing_operations_full has one row per operation"
vp_check "ts_parity:true" "v_test_sessions_full has one row per test session"
vp_check "op_out_only_in_view:1" "operation with only output_sample_id is in the view"
vp_check "ts_subject_only_in_view:1" "subject-only test session is in the view"
vp_check "ts_with_sample_code:TEST-VP-001" "sample columns are still filled when there is a sample"

echo "== Audit trail hardening (review 5.7) =="
run_eq "audit_trigger_function pins search_path" \
    "SELECT array_to_string(proconfig, ',') FROM pg_proc WHERE proname = 'audit_trigger_function'" \
    "search_path=pg_catalog, public"
run_eq "no role but the owner holds TRUNCATE on audit_logs" \
    "SELECT count(*) FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
     WHERE c.oid = 'public.audit_logs'::regclass AND a.privilege_type = 'TRUNCATE' AND a.grantee <> c.relowner" \
    "0"
tr_out=$($PSQL 2>&1 <<SQL
TRUNCATE audit_logs;
SQL
)
grep -q 'append-only' <<<"$tr_out" && ok "TRUNCATE audit_logs is rejected (even for the owner)" || bad "TRUNCATE audit_logs was not rejected (output: $tr_out)"
run "audit_logs still has rows after the TRUNCATE attempt" "SELECT 1 FROM audit_logs LIMIT 1"
# A schema placed ahead of public on the search_path must not capture the audit insert.
sp_out=$($PSQL 2>&1 <<SQL
BEGIN;
CREATE SCHEMA tc_shadow;
CREATE TABLE tc_shadow.audit_logs (LIKE public.audit_logs);
SET LOCAL search_path = tc_shadow, public;
INSERT INTO public.physical_samples (sample_code) VALUES ('TEST-SHADOW-001');
SELECT 'shadow:' || count(*) FROM tc_shadow.audit_logs;
SELECT 'real:' || count(*) FROM public.audit_logs WHERE row_after->>'sample_code' = 'TEST-SHADOW-001';
ROLLBACK;
SQL
)
grep -qx 'shadow:0' <<<"$sp_out" && grep -qx 'real:1' <<<"$sp_out" \
    && ok "audit row lands in public.audit_logs despite a shadowing schema" \
    || bad "search_path shadowing captured the audit write (output: $sp_out)"

echo "== Audit coverage: every business table, keyed by its primary key (review 5.3) =="
# Tables deliberately NOT audited: the log itself, dbmate bookkeeping, Directus system tables,
# derived caches (project_rollup, semantic_embeddings), the crawler's heartbeat row and
# audit_log_actors (the actor side-table of the log itself).
AUDIT_EXCLUDED="'audit_logs','audit_log_actors','schema_migrations','project_rollup','semantic_embeddings','force_crawler_state'"
run_eq "every business table has an audit trigger (missing: none)" \
    "SELECT coalesce(string_agg(c.relname, ', ' ORDER BY c.relname), '')
     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
       AND c.relname NOT LIKE 'directus\\_%' AND c.relname NOT IN ($AUDIT_EXCLUDED)
       AND NOT EXISTS (SELECT 1 FROM pg_trigger t
                       WHERE t.tgrelid = c.oid AND NOT t.tgisinternal
                         AND t.tgfoid = 'audit_trigger_function'::regproc
                         AND (t.tgtype & 1) = 1                -- FOR EACH ROW
                         AND (t.tgtype & 4) = 4 AND (t.tgtype & 8) = 8 AND (t.tgtype & 16) = 16)" \
    ""
run_eq "every audited table has a primary key (record_id is never 'unknown')" \
    "SELECT coalesce(string_agg(c.relname, ', ' ORDER BY c.relname), '')
     FROM pg_class c JOIN pg_trigger t ON t.tgrelid = c.oid AND t.tgfoid = 'audit_trigger_function'::regproc
     WHERE NOT t.tgisinternal
       AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary)" \
    ""

# INSERT / UPDATE / DELETE on tables that were unaudited before 20261003000121, in a rolled-back
# transaction. people has a UUID key, alloying_elements a text key.
au_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO people (person_id, full_name) VALUES ('c0000000-0000-4000-8000-0000000000f1', 'Audit Test Person');
UPDATE people SET full_name = 'Audit Test Renamed' WHERE person_id = 'c0000000-0000-4000-8000-0000000000f1';
DELETE FROM people WHERE person_id = 'c0000000-0000-4000-8000-0000000000f1';
INSERT INTO alloying_elements (symbol, element_name, atomic_number) VALUES ('Zz', 'Zzium', 999);
UPDATE alloying_elements SET element_name = 'Zzium2' WHERE symbol = 'Zz';
DELETE FROM alloying_elements WHERE symbol = 'Zz';
SELECT 'people_actions:' || string_agg(action_type, ',' ORDER BY log_id) FROM audit_logs
  WHERE table_name = 'people' AND record_id = 'c0000000-0000-4000-8000-0000000000f1';
SELECT 'people_changed:' || (changed_fields -> 'full_name' ->> 'old') || '>' || (changed_fields -> 'full_name' ->> 'new')
  FROM audit_logs WHERE table_name = 'people' AND action_type = 'UPDATE' AND record_id = 'c0000000-0000-4000-8000-0000000000f1';
SELECT 'people_delete_before:' || (row_before ->> 'full_name') FROM audit_logs
  WHERE table_name = 'people' AND action_type = 'DELETE' AND record_id = 'c0000000-0000-4000-8000-0000000000f1';
SELECT 'element_actions:' || string_agg(action_type, ',' ORDER BY log_id) FROM audit_logs
  WHERE table_name = 'alloying_elements' AND record_id = 'Zz';
SELECT 'element_changed:' || string_agg(k, ',' ORDER BY k) FROM audit_logs, jsonb_object_keys(changed_fields) AS k
  WHERE table_name = 'alloying_elements' AND action_type = 'UPDATE' AND record_id = 'Zz';
SELECT 'unknown_ids:' || count(*) FROM audit_logs WHERE record_id = 'unknown';
ROLLBACK;
SQL
)
au_check() { grep -qx "$1" <<<"$au_out" && ok "$2" || bad "$2 (psql output: $au_out)"; }
au_check "people_actions:INSERT,UPDATE,DELETE" "people: INSERT, UPDATE and DELETE each write an audit row keyed by person_id"
au_check "people_changed:Audit Test Person>Audit Test Renamed" "people: UPDATE records the changed field (old and new)"
au_check "people_delete_before:Audit Test Renamed" "people: DELETE keeps the row as it was"
au_check "element_actions:INSERT,UPDATE,DELETE" "alloying_elements: audit rows keyed by its text primary key (symbol)"
au_check "element_changed:element_name" "alloying_elements: UPDATE changed_fields lists exactly the changed columns"
au_check "unknown_ids:0" "no audit row is logged with record_id 'unknown'"

# record_id was a guess from a fixed column list: an operation was logged under its sample_id.
rid_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_methods (method_id, method_code, method_name)
VALUES ('c0000000-0000-4000-8000-0000000000a3', 'T-C-AU', 'audit record_id test method');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-0000000000d2', 'TEST-AU-001');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, pass_code)
VALUES ('c0000000-0000-4000-8000-0000000000c5', 'c0000000-0000-4000-8000-0000000000a3', 'c0000000-0000-4000-8000-0000000000d2', 'TEST-AU-OP');
INSERT INTO test_sessions (session_id, sample_id) VALUES ('c0000000-0000-4000-8000-0000000000e3', 'c0000000-0000-4000-8000-0000000000d2');
SELECT 'op_record_id:' || record_id FROM audit_logs WHERE table_name = 'manufacturing_operations' AND row_after ->> 'pass_code' = 'TEST-AU-OP';
SELECT 'ts_record_id:' || record_id FROM audit_logs WHERE table_name = 'test_sessions' AND row_after ->> 'session_id' = 'c0000000-0000-4000-8000-0000000000e3';
SELECT 'method_record_id:' || record_id FROM audit_logs WHERE table_name = 'manufacturing_methods' AND row_after ->> 'method_code' = 'T-C-AU';
ROLLBACK;
SQL
)
rid_check() { grep -qx "$1" <<<"$rid_out" && ok "$2" || bad "$2 (psql output: $rid_out)"; }
rid_check "op_record_id:c0000000-0000-4000-8000-0000000000c5" "operation audit rows carry operation_id, not sample_id"
rid_check "ts_record_id:c0000000-0000-4000-8000-0000000000e3" "test session audit rows carry session_id, not sample_id"
rid_check "method_record_id:c0000000-0000-4000-8000-0000000000a3" "newly audited manufacturing_methods carries method_id"

# machining_force_analysis: large derived envelopes are kept out of the audit snapshots.
mfa_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO directus_files (id) VALUES ('c0000000-0000-4000-8000-0000000000f2');
INSERT INTO manufacturing_methods (method_id, method_code, method_name)
VALUES ('c0000000-0000-4000-8000-0000000000a4', 'T-C-MF', 'mfa audit test method');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-0000000000d3', 'TEST-MF-001');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, pass_code)
VALUES ('c0000000-0000-4000-8000-0000000000c6', 'c0000000-0000-4000-8000-0000000000a4', 'c0000000-0000-4000-8000-0000000000d3', 'TEST-MF-OP');
INSERT INTO machining_force_analysis (id, operation_id, directus_files_id, series, fft, render_status)
VALUES ('c0000000-0000-4000-8000-0000000000f3', 'c0000000-0000-4000-8000-0000000000c6', 'c0000000-0000-4000-8000-0000000000f2',
        '{"fx":[1,2,3]}', '{"fx":[4,5,6]}', 'pending');
UPDATE machining_force_analysis SET render_status = 'done', series = '{"fx":[9,9,9]}' WHERE id = 'c0000000-0000-4000-8000-0000000000f3';
SELECT 'mfa_rows:' || count(*) FROM audit_logs WHERE table_name = 'machining_force_analysis' AND record_id = 'c0000000-0000-4000-8000-0000000000f3';
SELECT 'mfa_big_omitted:' || count(*) FROM audit_logs WHERE table_name = 'machining_force_analysis'
  AND record_id = 'c0000000-0000-4000-8000-0000000000f3'
  AND (coalesce(row_before, '{}') ?| ARRAY['series','fft','diag_metrics'] OR coalesce(row_after, '{}') ?| ARRAY['series','fft','diag_metrics']
       OR coalesce(changed_fields, '{}') ?| ARRAY['series','fft','diag_metrics']);
SELECT 'mfa_status_logged:' || (changed_fields -> 'render_status' ->> 'new') FROM audit_logs
  WHERE table_name = 'machining_force_analysis' AND action_type = 'UPDATE' AND record_id = 'c0000000-0000-4000-8000-0000000000f3';
ROLLBACK;
SQL
)
mfa_check() { grep -qx "$1" <<<"$mfa_out" && ok "$2" || bad "$2 (psql output: $mfa_out)"; }
mfa_check "mfa_rows:2" "machining_force_analysis: INSERT and UPDATE are audited"
mfa_check "mfa_big_omitted:0" "machining_force_analysis: series/fft/diag_metrics are left out of the snapshots"
mfa_check "mfa_status_logged:done" "machining_force_analysis: ordinary columns are still logged"

echo "== OCC triggers on every versioned table (review 5.4) =="
# schema_migrations.version is dbmate's bookkeeping column, not an OCC version.
run_eq "every table with a version column has an OCC BEFORE UPDATE trigger (missing: none)" \
    "SELECT coalesce(string_agg(c.relname, ', ' ORDER BY c.relname), '')
     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND c.relname <> 'schema_migrations'
       AND EXISTS (SELECT 1 FROM pg_attribute a
                   WHERE a.attrelid = c.oid AND a.attname = 'version' AND a.attnum > 0 AND NOT a.attisdropped)
       AND NOT EXISTS (SELECT 1 FROM pg_trigger t
                       WHERE t.tgrelid = c.oid AND NOT t.tgisinternal
                         AND t.tgfoid = 'occ_update_trigger_function'::regproc
                         AND (t.tgtype & 1) = 1 AND (t.tgtype & 2) = 2 AND (t.tgtype & 16) = 16)  -- ROW, BEFORE, UPDATE" \
    ""
# Stale-write detection as documented in docs/data-dictionary.md: UPDATE ... WHERE version = <known>
# matches no row once another writer has bumped the version. tool_setup and diag_layer had no
# trigger, so their version never moved and a stale write went through.
occ_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO tool_setup (setup_id, setup_code) VALUES ('c0000000-0000-4000-8000-0000000000f4', 'TEST-OCC-SETUP');
UPDATE tool_setup SET notes = 'writer one' WHERE setup_id = 'c0000000-0000-4000-8000-0000000000f4' AND version = 1;
WITH stale AS (
    UPDATE tool_setup SET notes = 'writer two (stale)'
    WHERE setup_id = 'c0000000-0000-4000-8000-0000000000f4' AND version = 1 RETURNING 1)
SELECT 'stale_rows:' || count(*) FROM stale;
SELECT 'version:' || version || ' notes:' || notes FROM tool_setup WHERE setup_id = 'c0000000-0000-4000-8000-0000000000f4';
ROLLBACK;
SQL
)
occ_check() { grep -qx "$1" <<<"$occ_out" && ok "$2" || bad "$2 (psql output: $occ_out)"; }
occ_check "stale_rows:0" "tool_setup: an update on a stale version matches no row"
occ_check "version:2 notes:writer one" "tool_setup: version is bumped once and the stale write did not land"

echo "== Box intake: owners propagate and codes survive a delete (review 4.8) =="
# expand_tool_box_intake() is called directly so the test does not depend on how it is triggered:
# the box is inserted with no package_quantity, then given one, then expanded.
bi_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO directus_users (id) VALUES ('c0000000-0000-4000-8000-0000000000f5');
INSERT INTO people (person_id, full_name) VALUES ('c0000000-0000-4000-8000-0000000000f6', 'Intake Owner');
INSERT INTO insert_types (insert_type_id, type_code, short_code, inserts_per_box, edge_count)
VALUES ('c0000000-0000-4000-8000-0000000000f7', 'TEST-INTAKE-TYPE', 'TST4', 2, 2);
INSERT INTO tool_boxes (tool_box_id, insert_type_id, owner, owner_person_id)
VALUES ('c0000000-0000-4000-8000-0000000000f8', 'c0000000-0000-4000-8000-0000000000f7',
        'c0000000-0000-4000-8000-0000000000f5', 'c0000000-0000-4000-8000-0000000000f6');
UPDATE tool_boxes SET package_quantity = 3 WHERE tool_box_id = 'c0000000-0000-4000-8000-0000000000f8';
SELECT expand_tool_box_intake('c0000000-0000-4000-8000-0000000000f8');
SELECT 'boxes:' || string_agg(tool_box_code, ',' ORDER BY tool_box_code) FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-0000000000f7';
SELECT 'inserts:' || count(*) FROM cutting_inserts WHERE insert_type_id = 'c0000000-0000-4000-8000-0000000000f7';
SELECT 'edges:' || count(*) FROM insert_edges e JOIN cutting_inserts i USING (insert_id) WHERE i.insert_type_id = 'c0000000-0000-4000-8000-0000000000f7';
SELECT 'owned_boxes:' || count(*) FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-0000000000f7'
  AND owner_person_id = 'c0000000-0000-4000-8000-0000000000f6' AND owner = 'c0000000-0000-4000-8000-0000000000f5';
SELECT 'owned_inserts:' || count(*) FROM cutting_inserts WHERE insert_type_id = 'c0000000-0000-4000-8000-0000000000f7'
  AND owner_person_id = 'c0000000-0000-4000-8000-0000000000f6' AND owner = 'c0000000-0000-4000-8000-0000000000f5';
SELECT 'owned_edges:' || count(*) FROM insert_edges e JOIN cutting_inserts i USING (insert_id) WHERE i.insert_type_id = 'c0000000-0000-4000-8000-0000000000f7'
  AND e.owner_person_id = 'c0000000-0000-4000-8000-0000000000f6' AND e.owner = 'c0000000-0000-4000-8000-0000000000f5';
-- Delete the middle box, then take in a second delivery of the same type.
DELETE FROM tool_boxes WHERE tool_box_code = 'TST4-2';
INSERT INTO tool_boxes (tool_box_id, insert_type_id) VALUES ('c0000000-0000-4000-8000-0000000000f9', 'c0000000-0000-4000-8000-0000000000f7');
UPDATE tool_boxes SET package_quantity = 2 WHERE tool_box_id = 'c0000000-0000-4000-8000-0000000000f9';
SELECT expand_tool_box_intake('c0000000-0000-4000-8000-0000000000f9');
SELECT 'boxes_after:' || string_agg(tool_box_code, ',' ORDER BY tool_box_code) FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-0000000000f7';
ROLLBACK;
SQL
)
bi_check() { grep -qx "$1" <<<"$bi_out" && ok "$2" || bad "$2 (psql output: $bi_out)"; }
bi_check "boxes:TST4-1,TST4-2,TST4-3" "intake of 3 creates TST4-1..3"
bi_check "inserts:6" "2 inserts per box x 3 boxes"
bi_check "edges:12" "2 edges per insert x 6 inserts"
bi_check "owned_boxes:3" "owner_person_id and owner are copied onto every box (clones included)"
bi_check "owned_inserts:6" "owner_person_id and owner are copied onto every insert"
bi_check "owned_edges:12" "owner_person_id and owner are copied onto every edge"
bi_check "boxes_after:TST4-1,TST4-3,TST4-4,TST4-5" "intake after a box delete continues from the highest code (no collision)"

echo "== Owner cascade runs in Postgres (review 4.7) =="
# A box with two inserts of two edges each, owned by person 1. Rolled back at the end.
oc_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO people (person_id, full_name) VALUES
    ('c0000000-0000-4000-8000-000000000101', 'Cascade Owner One'),
    ('c0000000-0000-4000-8000-000000000102', 'Cascade Owner Two');
INSERT INTO tool_boxes (tool_box_id, tool_box_code, owner_person_id)
VALUES ('c0000000-0000-4000-8000-000000000111', 'TEST-OC-BOX', 'c0000000-0000-4000-8000-000000000101');
INSERT INTO cutting_inserts (insert_id, insert_code, tool_box_id, owner_person_id) VALUES
    ('c0000000-0000-4000-8000-000000000121', 'TEST-OC-BOX-1', 'c0000000-0000-4000-8000-000000000111', 'c0000000-0000-4000-8000-000000000101'),
    ('c0000000-0000-4000-8000-000000000122', 'TEST-OC-BOX-2', 'c0000000-0000-4000-8000-000000000111', 'c0000000-0000-4000-8000-000000000101');
INSERT INTO insert_edges (edge_id, edge_code, insert_id, edge_identifier, owner_person_id) VALUES
    ('c0000000-0000-4000-8000-000000000131', 'TEST-OC-BOX-1A', 'c0000000-0000-4000-8000-000000000121', 'A', 'c0000000-0000-4000-8000-000000000101'),
    ('c0000000-0000-4000-8000-000000000132', 'TEST-OC-BOX-1B', 'c0000000-0000-4000-8000-000000000121', 'B', 'c0000000-0000-4000-8000-000000000101'),
    ('c0000000-0000-4000-8000-000000000133', 'TEST-OC-BOX-2A', 'c0000000-0000-4000-8000-000000000122', 'A', 'c0000000-0000-4000-8000-000000000101'),
    ('c0000000-0000-4000-8000-000000000134', 'TEST-OC-BOX-2B', 'c0000000-0000-4000-8000-000000000122', 'B', 'c0000000-0000-4000-8000-000000000101');

-- 1. Owner change WITHOUT the flag: children are left alone.
UPDATE tool_boxes SET owner_person_id = 'c0000000-0000-4000-8000-000000000102' WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111';
SELECT 'no_flag_children_unchanged:' || (SELECT count(*) FROM cutting_inserts WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111' AND owner_person_id = 'c0000000-0000-4000-8000-000000000101')
    || '/' || (SELECT count(*) FROM insert_edges WHERE owner_person_id = 'c0000000-0000-4000-8000-000000000101' AND edge_code LIKE 'TEST-OC-BOX-%');

-- 2. The flag, with the owner written in the same UPDATE (box 2 -> person 1 again).
UPDATE tool_boxes SET owner_person_id = 'c0000000-0000-4000-8000-000000000101', cascade_ownership = TRUE WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111';
UPDATE tool_boxes SET owner_person_id = 'c0000000-0000-4000-8000-000000000102', cascade_ownership = TRUE WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111';
SELECT 'box_cascade_inserts:' || count(*) FROM cutting_inserts WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111' AND owner_person_id = 'c0000000-0000-4000-8000-000000000102';
SELECT 'box_cascade_edges:' || count(*) FROM insert_edges WHERE edge_code LIKE 'TEST-OC-BOX-%' AND owner_person_id = 'c0000000-0000-4000-8000-000000000102';
SELECT 'box_flag_reset:' || NOT cascade_ownership FROM tool_boxes WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111';

-- 3. Insert-level flag only reaches that insert's edges.
UPDATE cutting_inserts SET owner_person_id = 'c0000000-0000-4000-8000-000000000101', cascade_ownership = TRUE WHERE insert_id = 'c0000000-0000-4000-8000-000000000121';
SELECT 'insert_cascade_own_edges:' || count(*) FROM insert_edges WHERE insert_id = 'c0000000-0000-4000-8000-000000000121' AND owner_person_id = 'c0000000-0000-4000-8000-000000000101';
SELECT 'insert_cascade_other_edges:' || count(*) FROM insert_edges WHERE insert_id = 'c0000000-0000-4000-8000-000000000122' AND owner_person_id = 'c0000000-0000-4000-8000-000000000102';
SELECT 'insert_flag_reset:' || NOT cascade_ownership FROM cutting_inserts WHERE insert_id = 'c0000000-0000-4000-8000-000000000121';

-- 4. Flag alone (owner not in the UPDATE): the stored owner is propagated.
UPDATE tool_boxes SET cascade_ownership = TRUE WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111';
SELECT 'stored_owner_edges:' || count(*) FROM insert_edges WHERE edge_code LIKE 'TEST-OC-BOX-%' AND owner_person_id = 'c0000000-0000-4000-8000-000000000102';

-- 5. A NULL owner is propagated as NULL.
UPDATE tool_boxes SET owner_person_id = NULL, cascade_ownership = TRUE WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111';
SELECT 'null_owner_inserts:' || count(*) FROM cutting_inserts WHERE tool_box_id = 'c0000000-0000-4000-8000-000000000111' AND owner_person_id IS NULL;
SELECT 'null_owner_edges:' || count(*) FROM insert_edges WHERE edge_code LIKE 'TEST-OC-BOX-%' AND owner_person_id IS NULL;

-- 6. The legacy owner column is never touched by the cascade.
SELECT 'legacy_owner_untouched:' || count(*) FROM insert_edges WHERE edge_code LIKE 'TEST-OC-BOX-%' AND owner IS NULL;
ROLLBACK;
SQL
)
oc_check() { grep -qx "$1" <<<"$oc_out" && ok "$2" || bad "$2 (psql output: $oc_out)"; }
oc_check "no_flag_children_unchanged:2/4" "owner change without cascade_ownership does not touch children"
oc_check "box_cascade_inserts:2" "box cascade: every insert gets the box's owner_person_id"
oc_check "box_cascade_edges:4" "box cascade: every edge of those inserts gets it too"
oc_check "box_flag_reset:true" "box cascade: cascade_ownership is reset to false"
oc_check "insert_cascade_own_edges:2" "insert cascade: the insert's edges get its owner_person_id"
oc_check "insert_cascade_other_edges:2" "insert cascade: other inserts' edges are untouched"
oc_check "insert_flag_reset:true" "insert cascade: cascade_ownership is reset to false"
oc_check "stored_owner_edges:4" "flag alone propagates the stored owner"
oc_check "null_owner_inserts:2" "a NULL owner is propagated to inserts"
oc_check "null_owner_edges:4" "a NULL owner is propagated to edges"
oc_check "legacy_owner_untouched:4" "the legacy owner column is not written by the cascade"

echo "== Box intake runs in Postgres (review 4.7) =="
bt_out=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO people (person_id, full_name) VALUES ('c0000000-0000-4000-8000-000000000201', 'Intake Trigger Owner');
INSERT INTO insert_types (insert_type_id, type_code, short_code, inserts_per_box, edge_count)
VALUES ('c0000000-0000-4000-8000-000000000211', 'TEST-INTAKE-TRIGGER', 'TST5', 2, 2);
-- The intake form: no code (placeholder default), a quantity and an owner.
INSERT INTO tool_boxes (tool_box_id, insert_type_id, package_quantity, owner_person_id)
VALUES ('c0000000-0000-4000-8000-000000000221', 'c0000000-0000-4000-8000-000000000211', 2, 'c0000000-0000-4000-8000-000000000201');
SELECT 'boxes:' || string_agg(tool_box_code, ',' ORDER BY tool_box_code) FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211';
SELECT 'inserts:' || count(*) FROM cutting_inserts WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211';
SELECT 'edges:' || count(*) FROM insert_edges e JOIN cutting_inserts i USING (insert_id) WHERE i.insert_type_id = 'c0000000-0000-4000-8000-000000000211';
SELECT 'clone_sentinel:' || string_agg(DISTINCT package_quantity::text, ',') FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211' AND tool_box_id <> 'c0000000-0000-4000-8000-000000000221';
SELECT 'owned_edges:' || count(*) FROM insert_edges e JOIN cutting_inserts i USING (insert_id)
  WHERE i.insert_type_id = 'c0000000-0000-4000-8000-000000000211' AND e.owner_person_id = 'c0000000-0000-4000-8000-000000000201';
-- The deleted box-intake hook stays loaded until Directus restarts and calls the function again
-- after the trigger already ran: the second call (on the renamed box 1 and on a clone) is a no-op.
SELECT expand_tool_box_intake('c0000000-0000-4000-8000-000000000221');
SELECT expand_tool_box_intake(tool_box_id) FROM tool_boxes
  WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211' AND tool_box_id <> 'c0000000-0000-4000-8000-000000000221';
SELECT 'boxes_second_call:' || string_agg(tool_box_code, ',' ORDER BY tool_box_code) FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211';
SELECT 'inserts_second_call:' || count(*) FROM cutting_inserts WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211';
SELECT 'edges_second_call:' || count(*) FROM insert_edges e JOIN cutting_inserts i USING (insert_id) WHERE i.insert_type_id = 'c0000000-0000-4000-8000-000000000211';
-- Writers that must NOT trigger an expansion: explicit code, NULL quantity, zero quantity, no insert type.
INSERT INTO tool_boxes (tool_box_code, insert_type_id, package_quantity) VALUES ('TEST-INTAKE-LEGACY', 'c0000000-0000-4000-8000-000000000211', 5);
INSERT INTO tool_boxes (insert_type_id) VALUES ('c0000000-0000-4000-8000-000000000211');
INSERT INTO tool_boxes (insert_type_id, package_quantity) VALUES ('c0000000-0000-4000-8000-000000000211', 0);
INSERT INTO tool_boxes (package_quantity) VALUES (3);
SELECT 'untouched_boxes:' || count(*) FROM tool_boxes WHERE insert_type_id = 'c0000000-0000-4000-8000-000000000211';
SELECT 'legacy_code_kept:' || count(*) FROM tool_boxes WHERE tool_box_code = 'TEST-INTAKE-LEGACY' AND package_quantity = 5;
SELECT 'no_type_box:' || count(*) FROM tool_boxes WHERE insert_type_id IS NULL AND package_quantity = 3 AND tool_box_code LIKE 'TMP-%';
ROLLBACK;
SQL
)
bt_check() { grep -qx "$1" <<<"$bt_out" && ok "$2" || bad "$2 (psql output: $bt_out)"; }
bt_check "boxes:TST5-1,TST5-2" "an intake row with a quantity expands into that many boxes"
bt_check "inserts:4" "2 boxes x 2 inserts are created"
bt_check "edges:8" "4 inserts x 2 edges are created"
bt_check "clone_sentinel:0" "clone boxes carry package_quantity = 0 (no re-expansion)"
bt_check "owned_edges:8" "owner_person_id reaches every edge through the trigger path"
bt_check "boxes_second_call:TST5-1,TST5-2" "a second expand_tool_box_intake() call creates no boxes and renames nothing"
bt_check "inserts_second_call:4" "a second call creates no inserts"
bt_check "edges_second_call:8" "a second call creates no edges"
bt_check "untouched_boxes:5" "explicit code, NULL, 0 quantity and typeless boxes are not expanded"
bt_check "legacy_code_kept:1" "a box with an explicit code and a quantity (legacy import) keeps both"
bt_check "no_type_box:1" "a quantity without an insert type is left alone, no error"
# Errors reach the writer: a type with no usable short code aborts the INSERT.
bt_err=$($PSQL 2>&1 <<SQL
BEGIN;
INSERT INTO insert_types (insert_type_id, type_code) VALUES ('c0000000-0000-4000-8000-000000000212', '---');
INSERT INTO tool_boxes (insert_type_id, package_quantity) VALUES ('c0000000-0000-4000-8000-000000000212', 1);
ROLLBACK;
SQL
)
grep -q 'cannot derive short_code' <<<"$bt_err" && ok "an expansion error aborts the INSERT and reaches the caller" || bad "expansion error was swallowed (output: $bt_err)"

echo "== Operation numbers and codes are assigned server-side (review 4.5) =="
# The trigger fills operation_sequence (max+1 per sample) and the {seq} / {mf} placeholders of a
# client-composed pass_code. Rolled-back transaction first: the numbers a new heat-treatment,
# deformation and additive operation get, a supplied number being kept, and the sintering counter.
seq_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_methods (method_id, method_code, method_name)
VALUES ('c0000000-0000-4000-8000-000000000401', 'T-I-HT', 'stream I test method');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000411', 'TI-S1');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000412', 'TI-S2');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000421', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000411', 'heat_treatment', 'TI-S1-HTA{seq}-800C_60min_AC');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000422', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000411', 'deformation', 'TI-S1-DR{seq}-20C_50pct');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000423', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000411', 'additive', 'TI-S1-AM{seq}-200W');
-- a machining pass number the user typed is kept, and the next blank one continues after it
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, operation_sequence, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000424', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000411', 'machining', 9, 'TI-S1-F9-20MPM');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000425', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000411', 'heat_treatment', 'TI-S1-HTS{seq}');
-- numbering is per sample, and a typed override without a placeholder is stored as given
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000426', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000412', 'heat_treatment', 'TI-S2-HTA{seq}');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000427', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000412', 'heat_treatment', 'MY-OWN-CODE');
-- no sample: the placeholder collapses to nothing and the sequence stays NULL (as before)
INSERT INTO manufacturing_operations (operation_id, method_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000428', 'c0000000-0000-4000-8000-000000000401', 'heat_treatment', 'test', 'TI-NOSAMPLE{seq}-X');
-- an imported row (source_system set) keeps a NULL sequence even with a sample; a later explicit
-- number is kept, so the importer's own numbering cannot collide with an auto-assigned one
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000429', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000412', 'sintering', 'test', 'TI-IMP{seq}-FAST');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, source_system, operation_sequence, pass_code)
VALUES ('c0000000-0000-4000-8000-00000000042a', 'c0000000-0000-4000-8000-000000000401', 'c0000000-0000-4000-8000-000000000412', 'machining', 'test', 1, 'TI-IMP-F1');
SELECT 'op:' || substr(operation_id::text, 33) || ':' || COALESCE(operation_sequence::text, 'null') || ':' || pass_code
FROM manufacturing_operations WHERE operation_id::text LIKE 'c0000000-0000-4000-8000-0000000004_%' ORDER BY operation_id;

-- sintering "MF" counter: max+1 over live codes, not count+1
SELECT COALESCE(max((substring(pass_code FROM '(?:^|-)MF(\d{1,9})(?:-|$)'))::bigint), 0) AS mfbase
FROM manufacturing_operations WHERE process_category = 'sintering' \gset
INSERT INTO manufacturing_operations (operation_id, method_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000431', 'c0000000-0000-4000-8000-000000000401', 'sintering', 'test', '01-01-26-MF' || (:mfbase + 5) || '-950C');
INSERT INTO manufacturing_operations (operation_id, method_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000432', 'c0000000-0000-4000-8000-000000000401', 'sintering', 'test', '02-01-26-MF{mf}-950C_11kN');
INSERT INTO manufacturing_operations (operation_id, method_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000433', 'c0000000-0000-4000-8000-000000000401', 'sintering', 'test', '03-01-26-MF{mf}');
DELETE FROM manufacturing_operations WHERE operation_id = 'c0000000-0000-4000-8000-000000000432';
INSERT INTO manufacturing_operations (operation_id, method_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000434', 'c0000000-0000-4000-8000-000000000401', 'sintering', 'test', '04-01-26-MF{mf}');
SELECT 'mf_explicit:' || (:mfbase + 5);
SELECT 'mf:' || substr(operation_id::text, 33) || ':' || pass_code FROM manufacturing_operations
WHERE operation_id::text LIKE 'c0000000-0000-4000-8000-00000000043_' ORDER BY operation_id;
-- regenerating the code of an existing operation must not store a raw placeholder
UPDATE manufacturing_operations SET pass_code = 'TI-S1-HTA{seq}-regen' WHERE operation_id = 'c0000000-0000-4000-8000-000000000421';
SELECT 'regen:' || pass_code || ':' || operation_sequence FROM manufacturing_operations WHERE operation_id = 'c0000000-0000-4000-8000-000000000421';
ROLLBACK;
SQL
)
seq_check() { grep -qx "$1" <<<"$seq_out" && ok "$2" || bad "$2 (psql output: $seq_out)"; }
seq_check "op:0421:1:TI-S1-HTA1-800C_60min_AC" "a new heat-treatment op gets sequence 1 and a code that carries it"
seq_check "op:0422:2:TI-S1-DR2-20C_50pct" "a new deformation op gets the next number, in its code too"
seq_check "op:0423:3:TI-S1-AM3-200W" "a new additive op gets the next number, in its code too"
seq_check "op:0424:9:TI-S1-F9-20MPM" "a supplied (machining pass) number is kept"
seq_check "op:0425:10:TI-S1-HTS10" "the next blank number continues after the highest one"
seq_check "op:0426:1:TI-S2-HTA1" "numbering restarts per sample"
seq_check "op:0427:2:MY-OWN-CODE" "a typed code without a placeholder is stored unchanged"
seq_check "op:0428:null:TI-NOSAMPLE-X" "an operation without a sample keeps a NULL sequence and an empty placeholder"
mf_exp=$(grep -m1 '^mf_explicit:' <<<"$seq_out" | cut -d: -f2)
seq_check "op:0429:null:TI-IMP-FAST" "an imported row (source_system set) is not auto-numbered, even with a sample"
seq_check "op:042a:1:TI-IMP-F1" "an imported row's explicit number is kept"
seq_check "mf:0431:01-01-26-MF${mf_exp}-950C" "an explicit MF number is stored as given"
seq_check "mf:0433:03-01-26-MF$((mf_exp + 2))" "the sintering MF counter is max+1 over existing codes"
seq_check "mf:0434:04-01-26-MF$((mf_exp + 3))" "an MF number is not handed out again after a delete"
seq_check "regen:TI-S1-HTA1-regen:1" "regenerating an existing code fills the placeholder from the stored sequence"

# Two writers at once: session A inserts and holds its transaction open, session B inserts for the
# same sample meanwhile. Without the advisory lock both read max = 0 and get 1.
cc_dir=$(mktemp -d)
$PSQL -q -c "
INSERT INTO manufacturing_methods (method_id, method_code, method_name)
VALUES ('c0000000-0000-4000-8000-000000000402', 'T-I-CC', 'stream I concurrency method');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000413', 'TI-CC1');" >/dev/null 2>&1
cc_insert() {  # cc_insert <op-id-suffix> <code> <hold-seconds>
    $PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-0000000004$1', 'c0000000-0000-4000-8000-000000000402',
        'c0000000-0000-4000-8000-000000000413', 'heat_treatment', '$2')
RETURNING operation_sequence || '|' || pass_code;
SELECT pg_sleep($3);
COMMIT;
SQL
}
cc_insert 51 'TI-CC1-HTA{seq}' 2 | grep '|' > "$cc_dir/a" &
sleep 0.7
cc_insert 52 'TI-CC1-HTA{seq}' 0 | grep '|' > "$cc_dir/b"
wait
cc_a=$(cat "$cc_dir/a"); cc_b=$(cat "$cc_dir/b")
[[ "$cc_a" == "1|TI-CC1-HTA1" && "$cc_b" == "2|TI-CC1-HTA2" ]] \
    && ok "concurrent inserts for one sample get distinct sequences and codes ($cc_a, $cc_b)" \
    || bad "concurrent inserts collided (A='$cc_a', B='$cc_b')"

# Same for the global sintering counter.
cc_mf() {  # cc_mf <op-id-suffix> <hold-seconds>
    $PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_operations (operation_id, method_id, process_category, source_system, pass_code)
VALUES ('c0000000-0000-4000-8000-0000000004$1', 'c0000000-0000-4000-8000-000000000402', 'sintering', 'test', '05-01-26-MF{mf}')
RETURNING pass_code;
SELECT pg_sleep($2);
COMMIT;
SQL
}
cc_mf 53 2 | grep MF > "$cc_dir/a" &
sleep 0.7
cc_mf 54 0 | grep MF > "$cc_dir/b"
wait
cc_a=$(cat "$cc_dir/a"); cc_b=$(cat "$cc_dir/b")
[[ -n "$cc_a" && -n "$cc_b" && "$cc_a" != "$cc_b" ]] \
    && ok "concurrent sintering inserts get distinct MF numbers ($cc_a, $cc_b)" \
    || bad "concurrent sintering inserts collided (A='$cc_a', B='$cc_b')"

# Bulk load: the per-sample lock must not use the shared lock table (advisory locks do, and
# ~13,000 samples in one transaction ran out of it). 400 samples, one operation each, one
# transaction: no per-sample advisory lock is held at the end, and each sample's number is 1.
bulk_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO physical_samples (sample_id, sample_code)
SELECT ('c0000000-0000-4000-8001-' || lpad(g::text, 12, '0'))::uuid, 'TI-BULK-' || g FROM generate_series(1, 400) g;
INSERT INTO manufacturing_operations (method_id, sample_id, process_category, pass_code)
SELECT 'c0000000-0000-4000-8000-000000000402', sample_id, 'heat_treatment', 'TI-BULK-HTA{seq}'
FROM physical_samples WHERE sample_code LIKE 'TI-BULK-%';
SELECT 'bulk_ops:' || count(*) || ':' || min(operation_sequence) || ':' || max(operation_sequence)
FROM manufacturing_operations WHERE pass_code = 'TI-BULK-HTA1';
SELECT 'bulk_advisory_locks:' || (count(*) <= 3) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'advisory';
ROLLBACK;
SQL
)
grep -qx "bulk_ops:400:1:1" <<<"$bulk_out" && grep -qx "bulk_advisory_locks:true" <<<"$bulk_out" \
    && ok "400 samples' operations in one transaction: numbered 1, no per-sample advisory locks" \
    || bad "bulk operation insert (psql output: $bulk_out)"

# Lock order (rollup -> sample -> MF/code): A writes an operation for sample X, holds its
# transaction open, then writes one for sample Y; B meanwhile writes one for Y. With the rollup lock
# taken after the sample lock, B holds Y and waits for the rollup lock that A holds while A waits
# for Y: "deadlock detected".
$PSQL -q -c "
INSERT INTO physical_samples (sample_id, sample_code) VALUES
    ('c0000000-0000-4000-8000-000000000414', 'TI-DLX'), ('c0000000-0000-4000-8000-000000000415', 'TI-DLY');" >/dev/null 2>&1
dl_a() {
    $PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000461', 'c0000000-0000-4000-8000-000000000402',
        'c0000000-0000-4000-8000-000000000414', 'heat_treatment', 'TI-DLX-HTA{seq}');
SELECT pg_sleep(2);
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000462', 'c0000000-0000-4000-8000-000000000402',
        'c0000000-0000-4000-8000-000000000415', 'heat_treatment', 'TI-DLY-HTA{seq}');
COMMIT;
SQL
}
dl_b() {
    $PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category, pass_code)
VALUES ('c0000000-0000-4000-8000-000000000463', 'c0000000-0000-4000-8000-000000000402',
        'c0000000-0000-4000-8000-000000000415', 'heat_treatment', 'TI-DLY-HTA{seq}');
COMMIT;
SQL
}
dl_a > "$cc_dir/dla" &
sleep 0.7
dl_b > "$cc_dir/dlb"
wait
dl_n=$($PSQL -c "SELECT count(*) FROM manufacturing_operations WHERE operation_id::text LIKE 'c0000000-0000-4000-8000-00000000046_'" 2>&1)
if ! grep -qi 'deadlock\|ERROR' "$cc_dir/dla" "$cc_dir/dlb" && [[ "$dl_n" == "3" ]]; then
    ok "operation writes for samples X,Y and Y do not deadlock (rollup lock is taken first)"
else
    bad "operation writes deadlocked or failed (A: $(cat "$cc_dir/dla"); B: $(cat "$cc_dir/dlb"); rows: $dl_n)"
fi

rm -rf "$cc_dir"
$PSQL -q -c "
DELETE FROM manufacturing_operations WHERE operation_id::text LIKE 'c0000000-0000-4000-8000-0000000004_%';
DELETE FROM physical_samples WHERE sample_id IN ('c0000000-0000-4000-8000-000000000413',
    'c0000000-0000-4000-8000-000000000414', 'c0000000-0000-4000-8000-000000000415');
DELETE FROM manufacturing_methods WHERE method_id = 'c0000000-0000-4000-8000-000000000402';" >/dev/null 2>&1 || true

echo "== Sample numbers are assigned server-side (review 4.6) =="
# A code written as {seq}-<rest> gets the next free number from the trigger; any other code is stored as given.
sc_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
SELECT COALESCE(max((substring(sample_code FROM '^(\d{1,9})-'))::bigint), 0) AS sbase FROM physical_samples \gset
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-000000000611', '{seq}-TI-MF-2026-10-4');
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-000000000612', '{seq}-TI-HT-2026-10-4');
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-000000000613', 'TI-HAND-TYPED');
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-000000000614', (:sbase + 500)::text || '-TI-OLD-2020-1-1');
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-000000000615', '{seq}-TI-MF-2026-10-5');
SELECT 'base:' || :sbase;
SELECT 'code:' || substr(sample_id::text, 33) || ':' || sample_code FROM physical_samples
WHERE sample_id::text LIKE 'c0000000-0000-4000-8000-00000000061_' ORDER BY sample_id;
-- "renumber": the row's own number is excluded, so it keeps the top slot rather than jumping past itself
UPDATE physical_samples SET sample_code = '{seq}-TI-MF-2026-10-5' WHERE sample_id = 'c0000000-0000-4000-8000-000000000615';
SELECT 'renumber:' || sample_code FROM physical_samples WHERE sample_id = 'c0000000-0000-4000-8000-000000000615';
-- an unrelated update leaves the code alone
UPDATE physical_samples SET nickname = 'x' WHERE sample_id = 'c0000000-0000-4000-8000-000000000611';
SELECT 'untouched:' || sample_code FROM physical_samples WHERE sample_id = 'c0000000-0000-4000-8000-000000000611';
ROLLBACK;
SQL
)
sc_check() { grep -qx "$1" <<<"$sc_out" && ok "$2" || bad "$2 (psql output: $sc_out)"; }
sc_base=$(grep -m1 '^base:' <<<"$sc_out" | cut -d: -f2)
sc_check "code:0611:$((sc_base + 1))-TI-MF-2026-10-4" "a {seq}- sample code gets max+1 and keeps the rest of the code"
sc_check "code:0612:$((sc_base + 2))-TI-HT-2026-10-4" "the next one gets the next number"
sc_check "code:0613:TI-HAND-TYPED" "a hand-typed code without the placeholder is stored as given"
sc_check "code:0614:$((sc_base + 500))-TI-OLD-2020-1-1" "an explicit number is stored as given"
sc_check "code:0615:$((sc_base + 501))-TI-MF-2026-10-5" "a later placeholder continues after the highest number in use"
sc_check "renumber:$((sc_base + 501))-TI-MF-2026-10-5" "renumbering excludes the row's own number"
sc_check "untouched:$((sc_base + 1))-TI-MF-2026-10-4" "an unrelated update does not renumber"

# Deploy-order guard: a placeholder that survives the trigger is rejected (NOT VALID checks).
ph_s=$($PSQL -q 2>&1 -c "INSERT INTO physical_samples (sample_code) VALUES ('TI-{seq}-MIDDLE')")
grep -q 'physical_samples_sample_code_no_placeholder_check' <<<"$ph_s" \
    && ok "a literal {seq} that the trigger does not replace is rejected" \
    || bad "literal {seq} sample code was not rejected (psql output: $ph_s)"
# With the trigger bypassed (as when the interface runs before the migration did) a literal
# placeholder hits the CHECK; one implicit transaction per -c, so nothing is left behind.
ph_o=$($PSQL -q 2>&1 -c "SET LOCAL session_replication_role = replica;
INSERT INTO manufacturing_operations (method_id, process_category, source_system, pass_code)
VALUES ((SELECT method_id FROM manufacturing_methods LIMIT 1), 'sintering', 'test', '05-01-26-MF{mf}')")
grep -q 'manufacturing_operations_pass_code_no_placeholder_check' <<<"$ph_o" \
    && ok "a literal {mf} / {seq} in pass_code is rejected when the trigger did not run" \
    || bad "literal {mf} pass_code was not rejected (psql output: $ph_o)"
ph_chk=$($PSQL -c "SELECT convalidated FROM pg_constraint WHERE conname IN ('physical_samples_sample_code_no_placeholder_check', 'manufacturing_operations_pass_code_no_placeholder_check')" | sort -u)
[[ "$ph_chk" == "f" ]] && ok "both placeholder checks are NOT VALID (existing rows are not scanned)" \
    || bad "placeholder check validity (got '$ph_chk')"

# Two registrations at once: A holds its transaction open while B inserts.
sc_dir=$(mktemp -d)
sc_insert() {  # sc_insert <id-suffix> <hold-seconds>
    $PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO physical_samples (sample_id, sample_code)
VALUES ('c0000000-0000-4000-8000-0000000006$1', '{seq}-TI-CC-2026-10-4') RETURNING sample_code;
SELECT pg_sleep($2);
COMMIT;
SQL
}
sc_insert 21 2 | grep TI-CC > "$sc_dir/a" &
sleep 0.7
sc_insert 22 0 | grep TI-CC > "$sc_dir/b"
wait
sc_a=$(cat "$sc_dir/a"); sc_b=$(cat "$sc_dir/b")
sc_na=${sc_a%%-*}; sc_nb=${sc_b%%-*}
[[ -n "$sc_na" && "$sc_nb" == "$((sc_na + 1))" ]] \
    && ok "concurrent registrations get distinct, consecutive sample numbers ($sc_a, $sc_b)" \
    || bad "concurrent registrations collided (A='$sc_a', B='$sc_b')"
rm -rf "$sc_dir"
$PSQL -q -c "DELETE FROM physical_samples WHERE sample_id::text LIKE 'c0000000-0000-4000-8000-0000000006__';" >/dev/null 2>&1 || true

echo "== Audit actor fallback from directus_activity (review 4.9) =="
# The actor-identity hook's set_config may not reach the write's transaction for PATCH/DELETE (see
# migration 20261003000128). Directus then still writes a directus_activity row in that transaction;
# the trigger on it attributes the audit rows. directus_activity is not a CI stub, so the test
# creates a minimal one inside the rolled-back transaction and installs the trigger with the
# migration's own DO block.
act_do=$(sed -n '/^-- migrate:up/,/^-- migrate:down/p' db/migrations/20261003000128_audit_actor_from_directus_activity.sql \
    | awk '/^DO \$\$/{f=1} f{print} f && /^\$\$;/{exit}')
[[ -n "$act_do" ]] && ok "found the migration's trigger-install block" || bad "could not extract the trigger-install block"
act_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
CREATE TABLE IF NOT EXISTS directus_activity (
    id serial PRIMARY KEY, action varchar(45), "user" uuid, collection varchar(64), item varchar(255),
    "timestamp" timestamptz DEFAULT now());
DROP TRIGGER IF EXISTS audit_actor_from_activity ON directus_activity;
$act_do
SELECT 'trigger:' || count(*) FROM pg_trigger WHERE tgname = 'audit_actor_from_activity' AND NOT tgisinternal;
-- 1. API-style write: no GUC (the hook could not reach this transaction), then Directus' activity rows
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000711', 'TI-ACT-1');
INSERT INTO directus_activity (action, "user", collection, item)
VALUES ('create', 'c0000000-0000-4000-8000-000000000799', 'physical_samples', 'c0000000-0000-4000-8000-000000000711');
UPDATE physical_samples SET nickname = 'renamed' WHERE sample_id = 'c0000000-0000-4000-8000-000000000711';
INSERT INTO directus_activity (action, "user", collection, item)
VALUES ('update', 'c0000000-0000-4000-8000-000000000799', 'physical_samples', 'c0000000-0000-4000-8000-000000000711');
SELECT 'raw_actor_null:' || count(*) FROM audit_logs
  WHERE record_id = 'c0000000-0000-4000-8000-000000000711' AND actor_identity IS NULL;
SELECT 'attributed:' || string_agg(action_type || '=' || actor_identity || '/' || actor_from_directus_activity, ',' ORDER BY log_id)
  FROM v_audit_logs_with_actor WHERE record_id = 'c0000000-0000-4000-8000-000000000711';
SELECT 'actor_rows:' || count(*) FROM audit_log_actors a JOIN audit_logs l USING (log_id)
  WHERE l.record_id = 'c0000000-0000-4000-8000-000000000711';
-- 2. an unauthenticated write is recorded as 'public'
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000712', 'TI-ACT-2');
INSERT INTO directus_activity (action, "user", collection, item)
VALUES ('create', NULL, 'physical_samples', 'c0000000-0000-4000-8000-000000000712');
SELECT 'public:' || actor_identity FROM v_audit_logs_with_actor WHERE record_id = 'c0000000-0000-4000-8000-000000000712';
-- 3. an audit row from an earlier transaction is never re-attributed
INSERT INTO audit_logs (table_name, record_id, action_type, event_timestamp)
VALUES ('physical_samples', 'TI-ACT-OLD', 'UPDATE', now() - interval '1 hour');
INSERT INTO directus_activity (action, "user", collection, item)
VALUES ('update', 'c0000000-0000-4000-8000-000000000799', 'physical_samples', 'TI-ACT-OLD');
SELECT 'old_rows:' || count(*) FROM audit_log_actors a JOIN audit_logs l USING (log_id) WHERE l.record_id = 'TI-ACT-OLD';
-- 4. a GUC-supplied actor wins and is not duplicated in the side table
SELECT set_config('d1.actor_identity', 'guc-user', true) \gset
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000713', 'TI-ACT-3');
INSERT INTO directus_activity (action, "user", collection, item)
VALUES ('create', 'c0000000-0000-4000-8000-000000000799', 'physical_samples', 'c0000000-0000-4000-8000-000000000713');
SELECT 'guc:' || actor_identity || '/' || actor_from_directus_activity FROM v_audit_logs_with_actor WHERE record_id = 'c0000000-0000-4000-8000-000000000713';
SELECT 'guc_rows:' || count(*) FROM audit_log_actors a JOIN audit_logs l USING (log_id) WHERE l.record_id = 'c0000000-0000-4000-8000-000000000713';
ROLLBACK;
SQL
)
act_check() { grep -qx "$1" <<<"$act_out" && ok "$2" || bad "$2 (psql output: $act_out)"; }
act_check "trigger:1" "the migration's block installs the directus_activity trigger"
act_check "raw_actor_null:2" "setup: the audit rows carried no actor (the hook could not reach the transaction)"
act_check "attributed:INSERT=c0000000-0000-4000-8000-000000000799/true,UPDATE=c0000000-0000-4000-8000-000000000799/true" "INSERT and UPDATE audit rows are attributed to the Directus user"
act_check "actor_rows:2" "one side-table row per attributed audit row, no duplicates"
act_check "public:public" "an unauthenticated write is attributed to 'public'"
act_check "old_rows:0" "an audit row from an earlier transaction is not re-attributed"
act_check "guc:guc-user/false" "an actor set through the GUC wins over the fallback"
act_check "guc_rows:0" "a GUC-attributed row gets no side-table row"

echo "== Process category comes from the method, in Postgres (review 4.11) =="
pc_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_methods (method_id, method_code, method_name, process_category) VALUES
  ('c0000000-0000-4000-8000-000000000801', 'T-I-PH', 'pc heat method', 'heat_treatment'),
  ('c0000000-0000-4000-8000-000000000802', 'T-I-PS', 'pc sinter method', 'sintering');
INSERT INTO manufacturing_methods (method_id, method_code, method_name) VALUES
  ('c0000000-0000-4000-8000-000000000803', 'T-I-PU', 'pc unmapped method'),
  ('c0000000-0000-4000-8000-000000000804', 'T-I-PV', 'pc unmapped method 2');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000811', 'TI-PC');
-- derived on insert when blank; an explicit value wins
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id) VALUES
  ('c0000000-0000-4000-8000-000000000821', 'c0000000-0000-4000-8000-000000000801', 'c0000000-0000-4000-8000-000000000811');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category) VALUES
  ('c0000000-0000-4000-8000-000000000822', 'c0000000-0000-4000-8000-000000000801', 'c0000000-0000-4000-8000-000000000811', 'deformation');
-- an unmapped method never blanks or invents a category
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, process_category) VALUES
  ('c0000000-0000-4000-8000-000000000823', 'c0000000-0000-4000-8000-000000000803', 'c0000000-0000-4000-8000-000000000811', 'machining');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id) VALUES
  ('c0000000-0000-4000-8000-000000000824', 'c0000000-0000-4000-8000-000000000803', 'c0000000-0000-4000-8000-000000000811');
UPDATE manufacturing_operations SET method_id = 'c0000000-0000-4000-8000-000000000804'
  WHERE operation_id = 'c0000000-0000-4000-8000-000000000823';
-- changing to a mapped method re-derives; setting the category in the same statement wins
UPDATE manufacturing_operations SET method_id = 'c0000000-0000-4000-8000-000000000802'
  WHERE operation_id = 'c0000000-0000-4000-8000-000000000821';
SELECT 'rederived:' || process_category FROM manufacturing_operations WHERE operation_id = 'c0000000-0000-4000-8000-000000000821';
UPDATE manufacturing_operations SET method_id = 'c0000000-0000-4000-8000-000000000802', process_category = 'additive'
  WHERE operation_id = 'c0000000-0000-4000-8000-000000000822';
-- an update that does not touch the method leaves the category alone, even if the method is mapped
UPDATE manufacturing_operations SET process_category = 'machining' WHERE operation_id = 'c0000000-0000-4000-8000-000000000821';
UPDATE manufacturing_operations SET outcome_notes = 'x' WHERE operation_id = 'c0000000-0000-4000-8000-000000000821';
SELECT 'cat:' || substr(operation_id::text, 33) || ':' || COALESCE(process_category, 'null')
FROM manufacturing_operations WHERE operation_id::text LIKE 'c0000000-0000-4000-8000-00000000082_' ORDER BY operation_id;
SELECT 'seed_MP:' || COALESCE(process_category, 'null') FROM manufacturing_methods WHERE method_code = 'MP';
SELECT 'seed_HT:' || COALESCE(process_category, 'null') FROM manufacturing_methods WHERE method_code = 'HT';
ROLLBACK;
SQL
)
pc_check() { grep -qx "$1" <<<"$pc_out" && ok "$2" || bad "$2 (psql output: $pc_out)"; }
pc_check "rederived:sintering" "changing the method re-derives the category (heat_treatment -> sintering)"
pc_check "cat:0821:machining" "a later edit of the category (method unchanged) is not overwritten"
pc_check "cat:0822:additive" "a category set in the same statement as a method change wins"
pc_check "cat:0823:machining" "an unmapped method never blanks a stored category"
pc_check "cat:0824:null" "an unmapped method on a blank category stays blank (nothing invented)"
pc_check "seed_MP:sample_prep" "the method map covers MP (sample preparation), which the old SQL map missed"
pc_check "seed_HT:heat_treatment" "the method map covers HT"
# insert-time derivation on its own (separate transaction so the later UPDATEs above cannot mask it)
pc2_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO manufacturing_methods (method_id, method_code, method_name, process_category)
VALUES ('c0000000-0000-4000-8000-000000000805', 'T-I-PW', 'pc method', 'additive');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000812', 'TI-PC2');
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id)
VALUES ('c0000000-0000-4000-8000-000000000825', 'c0000000-0000-4000-8000-000000000805', 'c0000000-0000-4000-8000-000000000812');
SELECT 'inserted:' || process_category FROM manufacturing_operations WHERE operation_id = 'c0000000-0000-4000-8000-000000000825';
ROLLBACK;
SQL
)
grep -qx "inserted:additive" <<<"$pc2_out" && ok "a new operation with no category gets its method's category on insert" || bad "insert-time derivation failed (output: $pc2_out)"

echo "== Prep recipes are applied in Postgres (review 4.12) =="
pr_out=$($PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO prep_recipes (recipe_id, name) VALUES
  ('c0000000-0000-4000-8000-000000000901', 'TI recipe A'),
  ('c0000000-0000-4000-8000-000000000902', 'TI recipe B'),
  ('c0000000-0000-4000-8000-000000000903', 'TI recipe empty');
INSERT INTO prep_recipe_steps (recipe_id, step_order, step_type, grit, duration_s) VALUES
  ('c0000000-0000-4000-8000-000000000901', 2, 'polishing', NULL, 120),
  ('c0000000-0000-4000-8000-000000000901', 1, 'grinding', 'P1200', 60),
  ('c0000000-0000-4000-8000-000000000902', 1, 'etching', NULL, 10);
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000911', 'TI-PR');
-- MP is the Sample Preparation method: its operations derive process_category = sample_prep
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, source_recipe_id)
SELECT 'c0000000-0000-4000-8000-000000000921', method_id, 'c0000000-0000-4000-8000-000000000911', 'c0000000-0000-4000-8000-000000000901'
FROM manufacturing_methods WHERE method_code = 'MP';
SELECT 'steps:' || string_agg(step_order || ':' || step_type || ':' || COALESCE(grit, '-'), ',' ORDER BY step_order)
FROM prep_steps WHERE operation_id = 'c0000000-0000-4000-8000-000000000921';
-- an operation that already has steps is not clobbered by a different recipe
UPDATE manufacturing_operations SET source_recipe_id = 'c0000000-0000-4000-8000-000000000902'
WHERE operation_id = 'c0000000-0000-4000-8000-000000000921';
SELECT 'steps_after_switch:' || count(*) FROM prep_steps WHERE operation_id = 'c0000000-0000-4000-8000-000000000921';
-- an empty recipe copies nothing and is not an error
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id, source_recipe_id)
SELECT 'c0000000-0000-4000-8000-000000000922', method_id, 'c0000000-0000-4000-8000-000000000911', 'c0000000-0000-4000-8000-000000000903'
FROM manufacturing_methods WHERE method_code = 'MP';
SELECT 'empty_recipe_steps:' || count(*) FROM prep_steps WHERE operation_id = 'c0000000-0000-4000-8000-000000000922';
-- setting a recipe on an existing prep operation without steps applies it
INSERT INTO manufacturing_operations (operation_id, method_id, sample_id)
SELECT 'c0000000-0000-4000-8000-000000000923', method_id, 'c0000000-0000-4000-8000-000000000911'
FROM manufacturing_methods WHERE method_code = 'MP';
UPDATE manufacturing_operations SET source_recipe_id = 'c0000000-0000-4000-8000-000000000902'
WHERE operation_id = 'c0000000-0000-4000-8000-000000000923';
SELECT 'late_apply_steps:' || count(*) FROM prep_steps WHERE operation_id = 'c0000000-0000-4000-8000-000000000923';
ROLLBACK;
SQL
)
pr_check() { grep -qx "$1" <<<"$pr_out" && ok "$2" || bad "$2 (psql output: $pr_out)"; }
pr_check "steps:1:grinding:P1200,2:polishing:-" "a prep operation created with a recipe gets its steps, in order"
pr_check "steps_after_switch:2" "existing steps are never clobbered by another recipe"
pr_check "empty_recipe_steps:0" "an empty recipe copies nothing"
pr_check "late_apply_steps:1" "setting a recipe on an existing prep operation without steps applies it"
# A recipe on anything but a Sample Preparation operation is rejected and the write is rolled back.
pr_err=$($PSQL -q 2>&1 <<SQL
BEGIN;
INSERT INTO prep_recipes (recipe_id, name) VALUES ('c0000000-0000-4000-8000-000000000904', 'TI recipe C');
INSERT INTO manufacturing_methods (method_id, method_code, method_name, process_category)
VALUES ('c0000000-0000-4000-8000-000000000905', 'T-I-PR', 'not a prep method', 'heat_treatment');
INSERT INTO physical_samples (sample_id, sample_code) VALUES ('c0000000-0000-4000-8000-000000000912', 'TI-PR2');
INSERT INTO manufacturing_operations (method_id, sample_id, source_recipe_id)
VALUES ('c0000000-0000-4000-8000-000000000905', 'c0000000-0000-4000-8000-000000000912', 'c0000000-0000-4000-8000-000000000904');
ROLLBACK;
SQL
)
grep -q 'only be set on a Sample Preparation operation' <<<"$pr_err" && ok "a recipe on a non-prep operation is rejected with a clear error" || bad "non-prep recipe was not rejected (output: $pr_err)"

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
