"""Schema-context builder tests (database mocked)."""

from unittest.mock import patch

from app.lib import ollama_client, schema_context


def _row(obj, comment, col, dtype, col_comment, pos):
    return {
        "object_name": obj,
        "object_comment": comment,
        "column_name": col,
        "data_type": dtype,
        "column_comment": col_comment,
        "column_position": pos,
    }


def test_build_system_prompt_lists_views_and_base_tables():
    dictionary = [
        _row("v_complete_sample_history", "Flat sample profile.", "sample_code", "text", "Human-readable sample label.", 1),
        _row("v_complete_sample_history", "Flat sample profile.", "mass_grams", "numeric", "Sample mass in grams.", 2),
        # A base table's columns are now included (broad read surface).
        _row("manufacturing_operations", "Ops.", "machining_feed_mm_per_rev", "numeric", "Feed per revolution.", 1),
    ]
    with patch.object(schema_context.db, "fetch_dictionary_all", return_value=dictionary):
        prompt = schema_context.build_system_prompt()

    assert "SELECT queries only" in prompt
    assert "v_complete_sample_history" in prompt
    assert "sample_code text" in prompt
    assert "Sample mass in grams." in prompt
    assert "machining_feed_mm_per_rev numeric" in prompt  # base-table column exposed


def test_build_system_prompt_excludes_denied_and_directus_tables():
    dictionary = [
        _row("physical_samples", "", "sample_code", "text", "", 1),
        _row("directus_users", "", "password", "text", "", 1),
        _row("directus_settings", "", "ai_openai_api_key", "text", "", 1),
        _row("directus_activity", "", "action", "text", "", 1),  # benign, but kept out of prompt
    ]
    with patch.object(schema_context.db, "fetch_dictionary_all", return_value=dictionary):
        prompt = schema_context.build_system_prompt()

    assert "physical_samples" in prompt
    assert "directus_users" not in prompt
    assert "password" not in prompt
    assert "ai_openai_api_key" not in prompt


def test_build_system_prompt_includes_known_values_legend():
    """Distinct values of low-cardinality text columns are listed; free text isn't."""
    schema_context._known_cache["ts"] = 0.0  # bypass the TTL cache
    dictionary = [
        _row("v_manufacturing_operations_full", "", "method_name", "text", "", 1),
        _row("v_manufacturing_operations_full", "", "outcome_notes", "text", "", 2),
    ]

    def fake_distinct(obj, col, cap=25):
        return {"method_name": ["Turning", "Milling"]}.get(col)

    with (
        patch.object(schema_context.db, "fetch_dictionary_all", return_value=dictionary),
        patch.object(schema_context.db, "distinct_values", side_effect=fake_distinct),
    ):
        prompt = schema_context.build_system_prompt()

    assert "Known column values" in prompt
    legend = prompt.split("Known column values")[1]
    assert "method_name: Turning, Milling" in legend
    assert "outcome_notes" not in legend  # free-text column skipped
    schema_context._known_cache["ts"] = 0.0  # don't leak cache to other tests


def test_strip_sql_fences():
    assert ollama_client.strip_sql_fences("```sql\nSELECT 1\n```") == "SELECT 1"
    assert ollama_client.strip_sql_fences("SELECT 1") == "SELECT 1"
    assert ollama_client.strip_sql_fences("```\nSELECT 2\n```") == "SELECT 2"
