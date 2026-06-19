"""Ollama HTTP client — chat completion and embeddings.

Talks to a local Ollama server (spec §6: self-hosted Llama-3/Mistral). No data
leaves the host. Models are configured via environment variables so the stack
can swap them without code changes.
"""

import os

import requests

OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://ollama:11434")
SQL_MODEL: str = os.getenv("OLLAMA_SQL_MODEL", "llama3")
EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
_TIMEOUT_S: int = int(os.getenv("OLLAMA_TIMEOUT_S", "120"))


def generate_sql(system_prompt: str, question: str) -> str:
    """Ask the chat model for a single SQL statement. Returns the raw text.

    Uses Ollama's /api/chat with streaming disabled. The caller is responsible
    for stripping markdown fences and validating the result through the SQL
    guard — nothing here is trusted.
    """
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": SQL_MODEL,
            "stream": False,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def embed(text: str) -> list[float]:
    """Return the embedding vector for *text* using the embedding model."""
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def strip_sql_fences(text: str) -> str:
    """Extract bare SQL from a model reply that may wrap it in markdown fences."""
    cleaned = text.strip()
    if "```" in cleaned:
        # Take the content of the first fenced block.
        parts = cleaned.split("```")
        block = parts[1] if len(parts) > 1 else cleaned
        # Drop an optional language tag on the first line (```sql).
        lines = block.splitlines()
        if lines and lines[0].strip().lower() in {"sql", "postgres", "postgresql"}:
            lines = lines[1:]
        cleaned = "\n".join(lines).strip()
    return cleaned
