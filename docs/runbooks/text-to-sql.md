# Runbook — Local Text-to-SQL & Semantic Search (Phase 6)

How to stand up, secure, and operate the local LLM text-to-SQL layer. Design
rationale is in [ADR-0009](../adr/0009-text-to-sql-guarded-readonly.md).

The capability has two halves:

- **Durable core** (already applied by migration `…0015_ai_readiness.sql`): the
  `v_schema_dictionary` / `v_llm_query_targets` views, the `semantic_embeddings`
  pgvector store, and the `d1_llm_readonly` read-only role.
- **Plugin** (`plugins/llm-text-to-sql/`, `llm` compose profile): a small API
  that turns a question into guarded SQL and rows, plus pgvector search and an
  embedding backfill. It depends on an **Ollama** runtime in the same profile.

---

## 1. One-time: create the read-only login role

The migration creates `d1_llm_readonly` as a NOLOGIN **privilege bundle** (SELECT
on the allow-listed views only; read-only + statement-timeout defaults). The
plugin must connect as a **login** role that *inherits* it. Create it once, with
a password kept out of version control:

```sql
-- as the d1 superuser, against the d1_database database
CREATE ROLE d1_llm_app LOGIN PASSWORD 'choose-a-strong-password' IN ROLE d1_llm_readonly;

-- Member roles do NOT inherit a group role's SET values, so pin them here too
-- (defence-in-depth; the plugin also enforces these per connection):
ALTER ROLE d1_llm_app SET default_transaction_read_only = on;
ALTER ROLE d1_llm_app SET statement_timeout = '5000ms';
```

Then set the DSNs in `.env`:

```
LLM_DATABASE_URL=postgres://d1_llm_app:choose-a-strong-password@postgres:5432/d1_database?sslmode=disable
EMBED_DATABASE_URL=postgres://d1:<d1-password>@postgres:5432/d1_database?sslmode=disable
```

- `LLM_DATABASE_URL` executes LLM-authored SQL — **never** point it at the
  superuser. It is the read-only, allow-listed login role above.
- `EMBED_DATABASE_URL` is used **only** by the embedding backfill, which must
  write `semantic_embeddings`; it needs INSERT/UPDATE on that one table.

> Verify the isolation any time with `make ai-test` (or
> `bash tests/phase6_text_to_sql.sh`): it provisions a throwaway member of
> `d1_llm_readonly` and asserts it can read the views but not base tables, the
> audit log, or write.

---

## 2. Start the LLM profile and pull models

Ollama and the plugin are in the opt-in `llm` profile so the heavy image and
models are not pulled by a default `docker compose up`.

```bash
docker compose --profile llm up -d ollama llm-text-to-sql

# Pull the models once (stored in the ollama-models volume):
docker compose exec ollama ollama pull llama3            # OLLAMA_SQL_MODEL
docker compose exec ollama ollama pull nomic-embed-text  # OLLAMA_EMBED_MODEL (768-dim)
```

Swap models via `OLLAMA_SQL_MODEL` / `OLLAMA_EMBED_MODEL` in `.env`. **Note:**
`semantic_embeddings.embedding` is `vector(768)`; only use an embedding model
that produces 768-dimensional vectors, or add a migration to change the column.

---

## 3. Ask a question

`POST /api/ask` on the plugin (host port `LLM_HTTP_PORT`, default `8082`). If
`WORKER_WEBHOOK_SECRET` is set, send it in `X-Worker-Secret`.

```bash
curl -s localhost:8082/api/ask \
  -H 'Content-Type: application/json' \
  -H "X-Worker-Secret: $WORKER_WEBHOOK_SECRET" \
  -d '{"question": "Which samples weigh more than 50 grams?"}' | jq
```

Response:

```json
{
  "sql": "SELECT sample_code, mass_grams FROM v_complete_sample_history WHERE mass_grams > 50",
  "columns": ["sample_code", "mass_grams"],
  "rows": [ ... ]
}
```

If the model emits unsafe or off-menu SQL the API returns **422** with the
rejection reason and the offending SQL — it is never executed. See ADR-0009 and
`app/lib/sql_guard.py` for the rules.

---

## 4. Embeddings & semantic search

Backfill embeddings for every note in the schema (incremental — unchanged notes
are skipped via `content_hash`):

```bash
curl -s -X POST localhost:8082/api/embed/backfill \
  -H "X-Worker-Secret: $WORKER_WEBHOOK_SECRET" | jq
# -> {"embedded": N, "skipped": M, "model": "nomic-embed-text"}
```

Run it after large note edits, or schedule it. Then search by meaning:

```bash
curl -s localhost:8082/api/search \
  -H 'Content-Type: application/json' \
  -H "X-Worker-Secret: $WORKER_WEBHOOK_SECRET" \
  -d '{"query": "cracking during sintering", "limit": 5}' | jq
```

Results come from `semantic_embeddings` ordered by cosine distance (the HNSW
index `semantic_embeddings_hnsw_idx`), each with its `source_table` /
`source_id` so you can click through to the record.

The embeddable note columns are defined by the `v_embeddings_source_notes` view.
To embed a new note column, add a `UNION ALL` branch to that view in a new
migration and re-run the backfill — no plugin change needed.

---

## 5. Evaluating NL→SQL quality

`eval/questions.json` holds curated `(question, gold_sql)` pairs.

```bash
# Offline: assert every gold query still passes the guard (CI runs this).
make llm-eval

# Live: send each question to a running plugin and report safe-and-runnable rate.
LLM_API_URL=http://localhost:8082 python plugins/llm-text-to-sql/eval/run_eval.py --live
```

Add questions as the schema grows; the offline check guarantees the gold answers
stay within the allow-list as views change.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/ask` 422 "outside the allow-list" | Model referenced a base table | Expected — the guard worked. Improve the prompt or add the view to `v_llm_query_targets` **and** `ALLOWED_RELATIONS` if it should be queryable. |
| `/api/ask` 500, "LLM_DATABASE_URL is not configured" | DSN unset | Set `LLM_DATABASE_URL` in `.env` (step 1). |
| `permission denied for table …` in logs | Login role lacks a needed view grant | Grant it in a migration to `d1_llm_readonly`; never grant base tables. |
| Embeddings: `expected 768 dimensions` | Embedding model dimension ≠ 768 | Use a 768-dim model or migrate the `vector(…)` size. |
| Ollama timeouts | Model not pulled / cold | `docker compose exec ollama ollama pull <model>`; raise `OLLAMA_TIMEOUT_S`. |
| Query killed at ~5 s | `statement_timeout` hit | Expected guardrail; refine the question or raise `LLM_STATEMENT_TIMEOUT_MS`. |
