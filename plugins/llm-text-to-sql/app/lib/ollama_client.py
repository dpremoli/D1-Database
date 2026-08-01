"""Ollama HTTP client — chat completion and embeddings.

Talks to a local Ollama server (spec §6: self-hosted Llama-3/Mistral). No data
leaves the host. Models are configured via environment variables so the stack
can swap them without code changes.
"""

import json
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
    return generate_sql_chat(system_prompt, [{"role": "user", "content": question}])


def generate_sql_chat(system_prompt: str, messages: list[dict]) -> str:
    """Multi-turn variant: generate SQL given a conversation history.

    *messages* is a list of ``{"role": "user"|"assistant", "content": str}`` in
    chronological order — the prior turns give the model context so a follow-up
    like "now only aluminium alloys" refines the previous query. The system
    prompt (the live schema dictionary) is prepended. Returns raw text; the
    caller strips fences and runs it through the SQL guard — nothing is trusted.
    """
    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend(
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    )
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": SQL_MODEL,
            "stream": False,
            "options": {"temperature": 0},
            "messages": chat_messages,
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


_CHART_SYSTEM_PROMPT = """\
You suggest ONE chart for a SQL result set, or none if a chart would not help.
Reply with ONLY a compact JSON object, no prose, no markdown fences.

Schema:
  {"type": "bar|line|scatter|histogram|pie|none",
   "x": "<column name>",
   "y": ["<column name>", ...],
   "title": "<short title>"}

Rules:
- Use ONLY the exact column names provided.
- "x" is the category/axis column; "y" lists the numeric value column(s).
- Use "histogram" for a single numeric column's distribution (y may be []).
- If the user asked for a specific chart type (pie, bar, line, scatter,
  histogram), you MUST use that exact type.
- If no chart is appropriate (e.g. a single row, or all text), return
  {"type": "none"}.
"""


def suggest_chart(
    columns: list[str], sample_rows: list[dict], question: str = ""
) -> dict | None:
    """Ask the model to propose a chart spec (JSON) for a result set.

    *question* is the user's latest request; passing it lets the model honour an
    explicit chart type ("make a pie chart"). Returns the parsed dict as-is
    (unvalidated) or ``None`` if the model returns nothing usable / not-JSON.
    Callers MUST pass the result through ``app.lib.charts.validate_chart_spec``
    before trusting it — this only parses.
    """
    if not columns or not sample_rows:
        return None
    preview = sample_rows[:20]
    user = (
        (f"User request: {question}\n" if question else "")
        + f"Columns: {json.dumps(columns)}\n"
        + f"Sample rows (up to 20): {json.dumps(preview, default=str)}\n"
        + "Return the chart JSON."
    )
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": SQL_MODEL,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": _CHART_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
            },
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        parsed = json.loads(content)
    except (requests.RequestException, KeyError, ValueError):
        # Network/HTTP error, unexpected shape, or non-JSON content -> no chart.
        return None
    if isinstance(parsed, dict) and parsed.get("type") == "none":
        return None
    return parsed if isinstance(parsed, dict) else None


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
