# `/plugins` — Project-specific compute (separate containers)

Everything volatile and lab-specific lives here, behind a documented,
Directus-agnostic contract — never inside the core. One folder per plugin
container:

| Plugin | Purpose | Phase |
|---|---|---|
| `heavy-data-worker/` | Memory-mapped parsing of 10–100 GB force files, stats, plots | 4 |
| `llm-text-to-sql/` | Local Ollama LLM + pgvector natural-language querying | 6 |
| `analysis/` | Per-project custom analysis (swappable template) | 5 |
| `equipment/` | Instrument / MATLAB (`ABFP`) acquisition adapters | 5 |

Plugins authenticate as machine users (API tokens), consume the published
contract only, and never couple to schema internals beyond it.
