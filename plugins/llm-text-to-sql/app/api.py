"""Text-to-SQL API.

Endpoints (all but /health require the X-Worker-Secret header):
  GET  /health             — liveness probe
  POST /api/ask            — {question} -> {sql, columns, rows} (NL -> SQL -> data)
  POST /api/chat           — {messages[]} -> {sql, columns, rows, chart} (multi-turn)
  POST /api/search         — {query, limit?} -> semantically similar note rows
  POST /api/embed/backfill — (re)embed all note text into semantic_embeddings

The LLM is never trusted: its SQL passes through app.lib.sql_guard before it
touches the read-only database role, and any chart it proposes passes through
app.lib.charts before it reaches the client. See ADR-0009.
"""

import logging
import os

from flask import Flask, jsonify, request

from app.lib import charts, db, embeddings, ollama_client, schema_context
from app.lib.security import check_secret
from app.lib.sql_guard import DEFAULT_ROW_LIMIT, SqlGuardError, guard, message_only

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Bounded execution-feedback self-correction (standard text-to-SQL hardening):
# when a generated query is rejected or fails to run, feed the error back to the
# model and let it fix itself, up to this many total attempts.
MAX_SQL_ATTEMPTS: int = int(os.getenv("LLM_MAX_SQL_ATTEMPTS", "3"))


def _correction_hint(error: str) -> str:
    """A corrective user turn: the real error + where columns actually live."""
    return (
        f"That SQL failed with: {error}\n"
        "Rewrite it as ONE valid read-only SELECT, using ONLY columns that exist "
        "on the exact table or view you select FROM (see the schema above). Note: "
        "detailed process parameters (machining feed/speed/depth, process_category, "
        "machining_operation_subtype) are columns on the BASE table "
        "manufacturing_operations, while method_name/method_code are on the v_* "
        "views — JOIN manufacturing_operations to a view if you need both. "
        "Output ONLY the corrected SQL."
    )


app = Flask(__name__)
app.before_request(check_secret)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


def _rejection_response(exc: SqlGuardError, candidate_sql: str):
    """The shared 422 for SQL the guard refuses — never executed. See ADR-0009."""
    log.warning("rejected LLM SQL: %s | sql=%r", exc, candidate_sql)
    return (
        jsonify(
            {
                "error": "generated SQL rejected",
                "reason": str(exc),
                "sql": candidate_sql,
            }
        ),
        422,
    )


def _query_error_response(exc: db.QueryExecutionError, candidate_sql: str):
    """The shared 422 for guarded SQL Postgres rejects at run time.

    The model referenced a column that doesn't exist, or the query timed out —
    its fault, not a server fault, so surface it as a message instead of a 500.
    """
    log.warning("query execution failed: %s | sql=%r", exc, candidate_sql)
    return (
        jsonify(
            {
                "error": "the generated query could not run",
                "reason": str(exc),
                "sql": candidate_sql,
            }
        ),
        422,
    )


@app.post("/api/ask")
def ask():
    """Natural-language question -> guarded SQL -> rows.

    Body: {"question": "...", "row_limit": <optional int>}
    """
    payload = request.get_json(force=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "missing question"}), 400
    row_limit = int(payload.get("row_limit", DEFAULT_ROW_LIMIT))

    system_prompt = schema_context.build_system_prompt()
    raw = ollama_client.generate_sql(system_prompt, question)
    candidate_sql = ollama_client.strip_sql_fences(raw)

    try:
        safe_sql = guard(candidate_sql, row_limit=row_limit)
    except SqlGuardError as exc:
        return _rejection_response(exc, candidate_sql)

    try:
        rows = db.run_select(safe_sql)
    except db.QueryExecutionError as exc:
        return _query_error_response(exc, candidate_sql)
    columns = list(rows[0].keys()) if rows else []
    return jsonify({"sql": candidate_sql, "columns": columns, "rows": rows})


@app.post("/api/chat")
def chat():
    """Multi-turn NL chat -> guarded SQL -> rows + an optional chart spec.

    Body: {"messages": [{"role": "user"|"assistant", "content": "..."}...],
           "row_limit": <optional int>}

    The prior turns give the model context so follow-ups refine the previous
    query. The generated SQL still passes the guard (unsafe -> 422, not run), and
    any proposed chart passes app.lib.charts before it is returned.
    """
    payload = request.get_json(force=True) or {}
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not any(
        (m or {}).get("role") == "user" and (m or {}).get("content", "").strip()
        for m in messages
    ):
        return jsonify({"error": "missing messages"}), 400
    row_limit = int(payload.get("row_limit", DEFAULT_ROW_LIMIT))
    question = next(
        (
            m["content"]
            for m in reversed(messages)
            if (m or {}).get("role") == "user" and (m or {}).get("content")
        ),
        "",
    )

    system_prompt = schema_context.build_system_prompt()

    # Execution-feedback self-correction loop: generate SQL, and on a guard
    # rejection or a run-time error, append the real error to the conversation
    # and let the model repair it — bounded by MAX_SQL_ATTEMPTS.
    convo = list(messages)
    candidate_sql: str = ""
    rows: list[dict] = []
    result_ok = False
    failure = None  # (responder, exc, sql) from the last failed attempt

    for _attempt in range(MAX_SQL_ATTEMPTS):
        raw = ollama_client.generate_sql_chat(system_prompt, convo)
        candidate_sql = ollama_client.strip_sql_fences(raw)

        # Greetings / off-topic: a table-free SELECT of a message -> plain reply.
        reply = message_only(candidate_sql)
        if reply is not None:
            return jsonify(
                {"sql": None, "columns": [], "rows": [], "chart": None, "reply": reply}
            )

        try:
            safe_sql = guard(candidate_sql, row_limit=row_limit)
        except SqlGuardError as exc:
            failure = (_rejection_response, exc, candidate_sql)
            convo += [
                {"role": "assistant", "content": candidate_sql},
                {"role": "user", "content": _correction_hint(str(exc))},
            ]
            continue

        try:
            rows = db.run_select(safe_sql)
        except db.QueryExecutionError as exc:
            failure = (_query_error_response, exc, candidate_sql)
            convo += [
                {"role": "assistant", "content": candidate_sql},
                {"role": "user", "content": _correction_hint(str(exc))},
            ]
            continue

        result_ok = True
        break

    if not result_ok:
        responder, exc, sql = failure
        return responder(exc, sql)

    columns = list(rows[0].keys()) if rows else []

    # Ask the model for a chart (honouring an explicit "pie/bar/…"), validate it
    # against the real columns, then fall back to a deterministic chart so an
    # explicit "make a chart" still yields one.
    chart = charts.validate_chart_spec(
        ollama_client.suggest_chart(columns, rows, question), columns
    )
    if chart is None:
        chart = charts.default_chart_for(columns, rows, question)

    return jsonify(
        {"sql": candidate_sql, "columns": columns, "rows": rows, "chart": chart}
    )


@app.post("/api/search")
def search():
    """Hybrid semantic search over unstructured note text.

    Body: {"query": "...", "limit": <optional int>}
    """
    payload = request.get_json(force=True) or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"error": "missing query"}), 400
    limit = int(payload.get("limit", 5))

    query_embedding = ollama_client.embed(query)
    results = db.semantic_search(query_embedding, limit=limit)
    # source_id is a UUID -> stringify for JSON.
    for r in results:
        r["source_id"] = str(r["source_id"])
    return jsonify({"results": results})


@app.post("/api/embed/backfill")
def embed_backfill():
    """Embed all note text into semantic_embeddings (incremental)."""
    summary = embeddings.backfill()
    return jsonify(summary)
