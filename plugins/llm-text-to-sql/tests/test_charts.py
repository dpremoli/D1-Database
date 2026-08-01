"""Chart-spec validation matrix — no chart spec is ever trusted as code.

Mirrors the guard's allow/deny discipline for the visualisation layer: a valid
spec is normalised; anything malformed, off-menu, or referencing a column the
query didn't return falls back to ``None`` (a table).
"""

from app.lib.charts import (
    chart_type_from_text,
    default_chart_for,
    validate_chart_spec,
)

COLUMNS = ["material", "sample_count", "mass_grams"]


def test_valid_bar_spec_passes_and_normalises():
    spec = {"type": "bar", "x": "material", "y": "sample_count", "title": " Counts "}
    out = validate_chart_spec(spec, COLUMNS)
    assert out == {
        "type": "bar",
        "x": "material",
        "y": ["sample_count"],  # single string normalised to a list
        "title": "Counts",  # trimmed
    }


def test_multi_series_y_list_passes():
    spec = {"type": "line", "x": "material", "y": ["sample_count", "mass_grams"]}
    out = validate_chart_spec(spec, COLUMNS)
    assert out["y"] == ["sample_count", "mass_grams"]
    assert "title" not in out  # optional and absent


def test_histogram_without_y_is_allowed():
    out = validate_chart_spec({"type": "histogram", "x": "mass_grams"}, COLUMNS)
    assert out == {"type": "histogram", "x": "mass_grams", "y": []}


def test_x_not_in_columns_rejected():
    assert validate_chart_spec({"type": "bar", "x": "nope", "y": "sample_count"}, COLUMNS) is None


def test_y_not_in_columns_rejected():
    spec = {"type": "bar", "x": "material", "y": ["sample_count", "ghost"]}
    assert validate_chart_spec(spec, COLUMNS) is None


def test_unknown_chart_type_rejected():
    assert validate_chart_spec({"type": "sankey", "x": "material", "y": "sample_count"}, COLUMNS) is None


def test_non_histogram_needs_a_y():
    assert validate_chart_spec({"type": "bar", "x": "material"}, COLUMNS) is None


def test_non_dict_specs_rejected():
    for bad in (None, "bar", ["bar"], 42):
        assert validate_chart_spec(bad, COLUMNS) is None


def test_missing_type_rejected():
    assert validate_chart_spec({"x": "material", "y": "sample_count"}, COLUMNS) is None


# --- deterministic fallback (default_chart_for) ---

FALLBACK_ROWS = [
    {"material_name": "Ti-64", "count": 59},
    {"material_name": "RR1000", "count": 18},
]


def test_chart_type_from_text_detects_explicit_type():
    assert chart_type_from_text("make a pie chart") == "pie"
    assert chart_type_from_text("show it as a LINE graph") == "line"
    assert chart_type_from_text("how many samples?") is None


def test_default_chart_picks_categorical_x_and_numeric_y():
    out = default_chart_for(["material_name", "count"], FALLBACK_ROWS, "make a chart")
    assert out == {"type": "bar", "x": "material_name", "y": ["count"]}


def test_default_chart_honours_requested_pie():
    out = default_chart_for(["material_name", "count"], FALLBACK_ROWS, "make a pie chart")
    assert out["type"] == "pie"
    assert out["x"] == "material_name"
    assert out["y"] == ["count"]


def test_default_chart_single_numeric_is_histogram():
    rows = [{"mass_grams": 1.0}, {"mass_grams": 2.5}]
    out = default_chart_for(["mass_grams"], rows, "distribution of mass")
    assert out == {"type": "histogram", "x": "mass_grams", "y": []}


def test_default_chart_none_without_numeric_column():
    rows = [{"a": "x", "b": "y"}]
    assert default_chart_for(["a", "b"], rows, "bar chart") is None


def test_default_chart_none_without_rows():
    assert default_chart_for(["material_name", "count"], [], "bar") is None
