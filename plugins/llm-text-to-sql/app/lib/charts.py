"""Chart-spec validation — the safety boundary for LLM-proposed visualisations.

The chat flow asks the model to *suggest* a chart for a result set. Like the SQL
it authors, that suggestion is never trusted: we accept only a small JSON object
describing a chart (type + which returned columns to plot), never code, and we
validate every field against the columns actually returned by the query. Anything
malformed, off-menu, or referencing a non-existent column yields ``None`` — the
frontend then renders the data as a plain table.

A spec is *data*, not executable code: the frontend maps it onto a fixed set of
Plotly traces. There is no eval path here.
"""

from __future__ import annotations

# The chart types the frontend knows how to render. Keep in sync with chat.vue.
ALLOWED_CHART_TYPES: frozenset[str] = frozenset(
    {"bar", "line", "scatter", "histogram", "pie"}
)

# Types that plot a single value/label pair rather than x against many y series.
_SINGLE_SERIES_TYPES: frozenset[str] = frozenset({"histogram", "pie"})


def validate_chart_spec(spec: object, columns: list[str]) -> dict | None:
    """Return a normalised, safe chart spec, or ``None`` to fall back to a table.

    A valid spec is a dict like::

        {"type": "bar", "x": "material", "y": ["sample_count"], "title": "..."}

    Rules (any failure -> ``None``):
      - ``type`` must be one of :data:`ALLOWED_CHART_TYPES`;
      - ``x`` must be a string naming a column present in *columns*;
      - ``y`` must name column(s) present in *columns*. It is normalised to a
        list. ``histogram`` may omit ``y`` (it bins ``x``); all other types need
        at least one valid ``y`` column;
      - ``title`` is optional and coerced to a trimmed string.

    Only known keys are emitted, so nothing extra reaches the frontend.
    """
    if not isinstance(spec, dict):
        return None

    chart_type = spec.get("type")
    if not isinstance(chart_type, str) or chart_type not in ALLOWED_CHART_TYPES:
        return None

    column_set = set(columns)

    x = spec.get("x")
    if not isinstance(x, str) or x not in column_set:
        return None

    y = _normalise_y(spec.get("y"), column_set)
    if y is None:
        return None
    if not y and chart_type not in _SINGLE_SERIES_TYPES:
        # bar/line/scatter/pie need something to plot on the value axis.
        return None

    result: dict = {"type": chart_type, "x": x, "y": y}

    title = spec.get("title")
    if isinstance(title, str) and title.strip():
        result["title"] = title.strip()

    return result


def chart_type_from_text(text: str) -> str | None:
    """Return the chart type the user explicitly asked for, if any."""
    lowered = (text or "").lower()
    for kind in ("pie", "line", "scatter", "histogram", "bar"):
        if kind in lowered:
            return kind
    return None


def default_chart_for(
    columns: list[str], rows: list[dict], question: str = ""
) -> dict | None:
    """A deterministic chart when the model declines but the data is chartable.

    Picks the first categorical column as ``x`` and the numeric column(s) as
    ``y`` (or a single numeric column as a histogram). Honours an explicit chart
    type in *question* ("pie"/"line"/…); otherwise defaults to a bar chart. This
    is the fallback so an explicit "make a chart" still yields one. Returns a
    spec already consistent with *columns*, or ``None`` if nothing fits.
    """
    if not columns or not rows:
        return None

    numeric = [c for c in columns if _is_numeric_column(c, rows)]
    categorical = [c for c in columns if c not in numeric]
    requested = chart_type_from_text(question)

    if not numeric:
        return None

    if requested == "histogram" or (not categorical and len(numeric) >= 1):
        return {"type": "histogram", "x": numeric[0], "y": []}

    x = categorical[0] if categorical else columns[0]
    y = [c for c in numeric if c != x][: 1 if requested == "pie" else None]
    if not y:
        return None
    return {"type": requested or "bar", "x": x, "y": y}


def _is_numeric_column(column: str, rows: list[dict]) -> bool:
    """True if every non-null value in *column* across *rows* is a number."""
    saw_value = False
    for row in rows:
        value = row.get(column)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        saw_value = True
    return saw_value


def _normalise_y(raw: object, column_set: set[str]) -> list[str] | None:
    """Coerce ``y`` to a list of valid column names, or ``None`` if any is bad.

    Accepts a single string or a list of strings. An empty/absent ``y`` returns
    ``[]`` (valid for histogram); a ``y`` naming a column not in *column_set*
    returns ``None`` so the whole spec is rejected.
    """
    if raw is None:
        return []
    candidates = [raw] if isinstance(raw, str) else raw
    if not isinstance(candidates, list):
        return None
    out: list[str] = []
    for item in candidates:
        if not isinstance(item, str) or item not in column_set:
            return None
        out.append(item)
    return out
