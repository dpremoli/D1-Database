"""Text-to-SQL API.

Endpoints (all but /health require the X-Worker-Secret header):
  GET  /health             — liveness probe
  POST /api/ask            — {question} -> {sql, columns, rows} (NL -> SQL -> data)
  POST /api/search         — {query, limit?} -> semantically similar note rows
  POST /api/embed/backfill — (re)embed all note text into semantic_embeddings

The LLM is never trusted: its SQL passes through app.lib.sql_guard before it
touches the read-only database role. See ADR-0009.
"""

import logging

from flask import Flask, jsonify, request

from app.lib import db, embeddings, ollama_client, schema_context
from app.lib.security import check_secret
from app.lib.sql_guard import DEFAULT_ROW_LIMIT, SqlGuardError, guard

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.before_request(check_secret)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


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

    rows = db.run_select(safe_sql)
    columns = list(rows[0].keys()) if rows else []
    return jsonify({"sql": candidate_sql, "columns": columns, "rows": rows})


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
