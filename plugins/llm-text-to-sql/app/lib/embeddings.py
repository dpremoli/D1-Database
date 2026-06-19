"""Embedding backfill — populate semantic_embeddings from note text.

Reads v_embeddings_source_notes (every embeddable note in the schema), embeds
each note via Ollama, and upserts into semantic_embeddings. content_hash makes
the backfill incremental: unchanged notes are skipped. This needs WRITE access,
so it uses EMBED_DATABASE_URL (a writer DSN), not the read-only LLM role.
"""

import hashlib
import logging
import os

import psycopg

from app.lib import ollama_client

log = logging.getLogger(__name__)

EMBED_DATABASE_URL: str = os.getenv("EMBED_DATABASE_URL", os.getenv("DATABASE_URL", ""))


def _connect() -> psycopg.Connection:
    if not EMBED_DATABASE_URL:
        raise RuntimeError("EMBED_DATABASE_URL (or DATABASE_URL) is not configured")
    return psycopg.connect(EMBED_DATABASE_URL)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backfill() -> dict:
    """Embed all source notes that are new or changed. Returns a summary dict."""
    model = ollama_client.EMBED_MODEL
    embedded = 0
    skipped = 0

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_table, source_id, source_column, content_text "
                "FROM v_embeddings_source_notes"
            )
            rows = cur.fetchall()

        for source_table, source_id, source_column, content_text in rows:
            content_hash = _hash(content_text)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content_hash FROM semantic_embeddings "
                    "WHERE source_table = %s AND source_id = %s "
                    "AND source_column = %s AND model_name = %s",
                    (source_table, source_id, source_column, model),
                )
                existing = cur.fetchone()

            if existing and existing[0] == content_hash:
                skipped += 1
                continue

            vector = ollama_client.embed(content_text)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO semantic_embeddings
                        (source_table, source_id, source_column, content_text,
                         content_hash, embedding, model_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_table, source_id, source_column, model_name)
                    DO UPDATE SET
                        content_text = EXCLUDED.content_text,
                        content_hash = EXCLUDED.content_hash,
                        embedding    = EXCLUDED.embedding,
                        updated_at   = now()
                    """,
                    (
                        source_table,
                        source_id,
                        source_column,
                        content_text,
                        content_hash,
                        str(vector),
                        model,
                    ),
                )
            embedded += 1
        conn.commit()

    log.info("embedding backfill: %d embedded, %d unchanged", embedded, skipped)
    return {"embedded": embedded, "skipped": skipped, "model": model}
