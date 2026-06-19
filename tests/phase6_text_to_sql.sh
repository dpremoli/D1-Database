#!/usr/bin/env bash
# Phase 6 AI-readiness test: verifies the durable-core half of the text-to-SQL
# capability — the semantic dictionary view, the LLM query-target menu, the
# pgvector embedding store, and the read-only role's grant isolation (the LLM
# login role can read the allow-listed views but NOT base tables, the audit log,
# or write anything).
# Requires a running Postgres with DATABASE_URL set (superuser, to create roles),
# or a local stack via `make up`.
#
# Usage:  DATABASE_URL=postgres://d1:pw@localhost:5432/d1_db bash tests/phase6_text_to_sql.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

: "${DATABASE_URL:?DATABASE_URL must be set (e.g. postgres://d1:pw@localhost:5432/d1_db)}"
PSQL="psql $DATABASE_URL --no-psqlrc -t -A"

# A login role that inherits the d1_llm_readonly group — this is exactly what the
# runbook tells the operator to create for the plugin. Read-only + statement
# timeout are pinned here too (group-role SETs are not inherited by members).
LLM_USER="phase6_llm_app"
LLM_PW="phase6_pw"

cleanup() { $PSQL -c "DROP ROLE IF EXISTS $LLM_USER" >/dev/null 2>&1; }
trap cleanup EXIT

pass=0; fail=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
run_eq() {
    local label="$1" sql="$2" expected="$3" result
    result=$($PSQL -c "$sql" 2>&1) || { bad "$label (psql error: $result)"; return; }
    [[ "$result" == "$expected" ]] && ok "$label" || bad "$label (got '$result', want '$expected')"
}
# Assert a query run as the LLM login role FAILS (permission denied / read-only).
deny() {
    local label="$1" sql="$2" out
    out=$(PGPASSWORD="$LLM_PW" psql "${LLM_DSN}" --no-psqlrc -t -A -c "$sql" 2>&1)
    if [[ $? -ne 0 ]]; then ok "$label (denied: ${out##*ERROR:  })"; else bad "$label (UNEXPECTEDLY ALLOWED)"; fi
}
allow() {
    local label="$1" sql="$2" out
    out=$(PGPASSWORD="$LLM_PW" psql "${LLM_DSN}" --no-psqlrc -t -A -c "$sql" 2>&1)
    if [[ $? -eq 0 ]]; then ok "$label"; else bad "$label (error: $out)"; fi
}

echo "== AI-readiness objects exist =="
run_eq "v_schema_dictionary view exists" \
    "SELECT 'y' FROM pg_views WHERE viewname='v_schema_dictionary'" "y"
run_eq "v_llm_query_targets view exists" \
    "SELECT 'y' FROM pg_views WHERE viewname='v_llm_query_targets'" "y"
run_eq "v_embeddings_source_notes view exists" \
    "SELECT 'y' FROM pg_views WHERE viewname='v_embeddings_source_notes'" "y"
run_eq "semantic_embeddings table exists" \
    "SELECT 'y' FROM pg_tables WHERE tablename='semantic_embeddings'" "y"
run_eq "hnsw vector index exists" \
    "SELECT 'y' FROM pg_indexes WHERE indexname='semantic_embeddings_hnsw_idx'" "y"
run_eq "d1_llm_readonly role exists" \
    "SELECT 'y' FROM pg_roles WHERE rolname='d1_llm_readonly'" "y"

echo "== Semantic dictionary is populated =="
run_eq "dictionary has the sample-history view's columns" \
    "SELECT CASE WHEN COUNT(*) > 5 THEN 'y' ELSE 'n' END
     FROM v_schema_dictionary WHERE object_name='v_complete_sample_history'" "y"
run_eq "dictionary carries column comments" \
    "SELECT CASE WHEN COUNT(*) > 0 THEN 'y' ELSE 'n' END
     FROM v_schema_dictionary WHERE column_comment IS NOT NULL" "y"

echo "== Query-target menu is the data views only =="
run_eq "menu lists v_complete_sample_history" \
    "SELECT 'y' FROM v_llm_query_targets WHERE view_name='v_complete_sample_history'" "y"
run_eq "menu excludes the internal embeddings source" \
    "SELECT COALESCE(MAX('y'),'n') FROM v_llm_query_targets
     WHERE view_name='v_embeddings_source_notes'" "n"

echo "== Read-only role config is set (defence-in-depth) =="
run_eq "role is default_transaction_read_only" \
    "SELECT 'y' FROM pg_roles WHERE rolname='d1_llm_readonly'
       AND 'default_transaction_read_only=on' = ANY(rolconfig)" "y"
run_eq "role has a statement_timeout" \
    "SELECT 'y' FROM pg_roles WHERE rolname='d1_llm_readonly'
       AND EXISTS (SELECT 1 FROM unnest(rolconfig) AS c
                   WHERE c LIKE 'statement_timeout=%')" "y"

echo "== Grant isolation: provision a login member like the runbook does =="
$PSQL -c "DROP ROLE IF EXISTS $LLM_USER" >/dev/null 2>&1
$PSQL -c "CREATE ROLE $LLM_USER LOGIN PASSWORD '$LLM_PW' IN ROLE d1_llm_readonly" >/dev/null 2>&1
# Pin read-only + timeout on the login role (member roles do NOT inherit group SETs).
$PSQL -c "ALTER ROLE $LLM_USER SET default_transaction_read_only = on" >/dev/null 2>&1
$PSQL -c "ALTER ROLE $LLM_USER SET statement_timeout = '5000ms'" >/dev/null 2>&1

# Build a DSN for the LLM login role from the host/port/db of DATABASE_URL.
LLM_DSN=$($PSQL -c "SELECT regexp_replace(
    '$DATABASE_URL',
    '://[^@]+@',
    '://$LLM_USER:$LLM_PW@')")

allow "LLM role reads an allow-listed view" \
    "SELECT count(*) FROM v_complete_sample_history"
allow "LLM role reads the schema dictionary" \
    "SELECT count(*) FROM v_schema_dictionary"
deny  "LLM role cannot read base table physical_samples" \
    "SELECT count(*) FROM physical_samples"
deny  "LLM role cannot read the audit log" \
    "SELECT count(*) FROM audit_logs"
deny  "LLM role cannot read the embeddings backfill source" \
    "SELECT count(*) FROM v_embeddings_source_notes"
deny  "LLM role cannot write a core table" \
    "INSERT INTO physical_samples (sample_code, form) VALUES ('PHASE6-X','coupon')"
deny  "LLM role is read-only (no temp table create)" \
    "CREATE TEMP TABLE t (x int)"

echo "== pgvector similarity search works =="
# A 768-dim probe vector; cosine-orders the (possibly empty) embedding set.
run_eq "cosine <=> query executes against semantic_embeddings" \
    "SELECT 'y' FROM (
       SELECT embedding_id FROM semantic_embeddings
       ORDER BY embedding <=> ('['||array_to_string(array_fill(0.1::real, ARRAY[768]),',')||']')::vector
       LIMIT 1
     ) AS _probe
     UNION ALL SELECT 'y' LIMIT 1" "y"

echo
echo "Phase 6: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
