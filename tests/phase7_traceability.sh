#!/usr/bin/env bash
# Phase 7 traceability test: verifies the recursive lineage functions walk a
# sample's genealogy forward and backward without dead ends, resolve raw-stock
# origins, and produce a chronological event timeline.
# Requires a running Postgres with DATABASE_URL set, or a local stack via `make up`.
#
# Usage:  DATABASE_URL=postgres://d1:secret@localhost:5432/d1_test bash tests/phase7_traceability.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

: "${DATABASE_URL:?DATABASE_URL must be set (e.g. postgres://d1:pw@localhost:5432/d1_db)}"
PSQL="psql $DATABASE_URL --no-psqlrc -t -A -v ON_ERROR_STOP=1"

pass=0; fail=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
run_eq() {
    local label="$1" sql="$2" expected="$3" result
    result=$($PSQL -c "$sql" 2>&1) || { bad "$label (psql error: $result)"; return; }
    [[ "$result" == "$expected" ]] && ok "$label" || bad "$label (got '$result', want '$expected')"
}

# The fixture rows below are removed again on exit (also after a failure or Ctrl-C), and any
# leftovers of an earlier killed run are removed first. Only the P7-* rows this script creates
# are touched. Rows written to audit_logs stay: it is append-only by design.
FIXTURE_CODES="'P7-BILLET','P7-DISC','P7-PIECE-A','P7-PIECE-B'"
cleanup_fixture() {
    $PSQL -c "
BEGIN;
DELETE FROM test_sessions            WHERE sample_id IN (SELECT sample_id FROM physical_samples WHERE sample_code IN ($FIXTURE_CODES));
DELETE FROM manufacturing_operations WHERE sample_id IN (SELECT sample_id FROM physical_samples WHERE sample_code IN ($FIXTURE_CODES));
DELETE FROM sample_stock_provenance  WHERE sample_id IN (SELECT sample_id FROM physical_samples WHERE sample_code IN ($FIXTURE_CODES))
                                        OR lot_id IN (SELECT lot_id FROM raw_stock_lots WHERE lot_code = 'P7-LOT-001');
DELETE FROM sample_genealogy         WHERE child_sample_id  IN (SELECT sample_id FROM physical_samples WHERE sample_code IN ($FIXTURE_CODES))
                                        OR parent_sample_id IN (SELECT sample_id FROM physical_samples WHERE sample_code IN ($FIXTURE_CODES));
DELETE FROM physical_samples         WHERE sample_code IN ($FIXTURE_CODES);
DELETE FROM raw_stock_lots           WHERE lot_code = 'P7-LOT-001';
COMMIT;" >/dev/null
}
on_exit() {
    local status=$? err
    if ! err=$(cleanup_fixture 2>&1 >/dev/null); then
        printf '\033[31mFAIL\033[0m could not remove the P7-* fixture rows: %s\n' "$err" >&2
        status=1
    fi
    exit "$status"
}
trap on_exit EXIT

echo "== Traceability functions exist =="
for fn in f_trace_ancestors f_trace_descendants f_trace_stock_origins f_sample_timeline; do
    run_eq "$fn exists" \
        "SELECT proname FROM pg_proc WHERE proname = '$fn'" "$fn"
done

echo "== Build an isolated lineage fixture (BILLET → DISC → PIECE-A/B) =="
if ! cleanup_fixture >/dev/null 2>&1; then
    bad "could not clear leftover P7-* fixture rows from an earlier run"
    echo "Phase 7: $pass passed, $fail failed"
    exit 1
fi
# One DO block = one transaction: either the whole fixture exists or none of it. A failure
# here is fatal (every later check depends on it), not something to swallow.
if ! fixture_err=$($PSQL -c "
DO \$\$
DECLARE v_lot uuid; v_mid uuid; v_mat uuid;
        v_billet uuid; v_disc uuid; v_pa uuid; v_pb uuid;
BEGIN
  SELECT material_id INTO v_mat FROM materials LIMIT 1;
  SELECT method_id   INTO v_mid FROM manufacturing_methods LIMIT 1;
  INSERT INTO raw_stock_lots (lot_code, stock_type, supplier_name, material_id,
                              inbound_mass_grams, remaining_mass_grams)
    VALUES ('P7-LOT-001','billet','P7Supplier', v_mat, 10000, 5000)
    RETURNING lot_id INTO v_lot;
  INSERT INTO physical_samples (sample_code, form) VALUES ('P7-BILLET','billet') RETURNING sample_id INTO v_billet;
  INSERT INTO physical_samples (sample_code, form) VALUES ('P7-DISC','disc')     RETURNING sample_id INTO v_disc;
  INSERT INTO physical_samples (sample_code, form) VALUES ('P7-PIECE-A','coupon') RETURNING sample_id INTO v_pa;
  INSERT INTO physical_samples (sample_code, form) VALUES ('P7-PIECE-B','coupon') RETURNING sample_id INTO v_pb;
  INSERT INTO sample_genealogy (child_sample_id,parent_sample_id,relationship_type) VALUES
    (v_disc,v_billet,'cut_from'), (v_pa,v_disc,'cut_from'), (v_pb,v_disc,'cut_from');
  INSERT INTO sample_stock_provenance (sample_id,lot_id,mass_used_grams) VALUES (v_billet,v_lot,5000);
  INSERT INTO manufacturing_operations (sample_id,method_id,pass_code,operation_date,operator_name)
    VALUES (v_pa,v_mid,'P7-PIECE-A-F1','2026-01-10','alice');
  -- Use 'registered' (valid under both the old and new status constraints) so
  -- the CI full-rollback reversibility check is not blocked by this fixture row.
  INSERT INTO test_sessions (sample_id,test_type,session_date,status)
    VALUES (v_pa,'other','2026-01-12','registered');
END \$\$;
" 2>&1 >/dev/null); then
    bad "fixture creation failed: $fixture_err"
    echo "Phase 7: $pass passed, $fail failed (fixture missing; remaining checks skipped)"
    exit 1
fi
ok "fixture created"

PA="(SELECT sample_id FROM physical_samples WHERE sample_code='P7-PIECE-A')"
BILLET="(SELECT sample_id FROM physical_samples WHERE sample_code='P7-BILLET')"

echo "== Reverse traceability (ancestors) =="
run_eq "PIECE-A has 3 ancestor rows (self + DISC + BILLET)" \
    "SELECT count(*) FROM f_trace_ancestors($PA)" "3"
run_eq "PIECE-A root ancestor is the billet" \
    "SELECT sample_code FROM f_trace_ancestors($PA) ORDER BY depth DESC LIMIT 1" "P7-BILLET"

echo "== Cradle: raw-stock origins =="
run_eq "PIECE-A traces back to the originating lot" \
    "SELECT lot_code FROM f_trace_stock_origins($PA)" "P7-LOT-001"

echo "== Forward traceability (descendants) =="
run_eq "BILLET has 4 descendant rows (self + DISC + 2 pieces)" \
    "SELECT count(*) FROM f_trace_descendants($BILLET)" "4"
run_eq "BILLET reaches PIECE-A at depth 2" \
    "SELECT depth FROM f_trace_descendants($BILLET) WHERE sample_code='P7-PIECE-A'" "2"

echo "== Chronological timeline =="
run_eq "PIECE-A timeline has 2 events" \
    "SELECT count(*) FROM f_sample_timeline($PA)" "2"
run_eq "First timeline event is the manufacturing operation" \
    "SELECT event_type FROM f_sample_timeline($PA) ORDER BY event_date LIMIT 1" \
    "manufacturing_operation"

echo
echo "Phase 7: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
