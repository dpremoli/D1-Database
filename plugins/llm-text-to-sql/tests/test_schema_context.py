"""Schema-context builder tests (database mocked)."""

from unittest.mock import patch

from app.lib import ollama_client, schema_context


def test_build_system_prompt_lists_views_and_columns():
    targets = [
        {
            "view_name": "v_complete_sample_history",
            "description": "Flat sample profile.",
        },
    ]
    dictionary = [
        {
            "object_name": "v_complete_sample_history",
            "object_comment": "Flat sample profile.",
            "column_name": "sample_code",
            "data_type": "text",
            "column_comment": "Human-readable sample label.",
        },
        {
            "object_name": "v_complete_sample_history",
            "object_comment": "Flat sample profile.",
            "column_name": "mass_grams",
            "data_type": "numeric",
            "column_comment": "Sample mass in grams.",
        },
    ]
    with (
        patch.object(schema_context.db, "fetch_query_targets", return_value=targets),
        patch.object(schema_context.db, "fetch_dictionary", return_value=dictionary),
    ):
        prompt = schema_context.build_system_prompt()

    assert "SELECT queries only" in prompt
    assert "v_complete_sample_history" in prompt
    assert "sample_code text" in prompt
    assert "Sample mass in grams." in prompt


def test_build_system_prompt_ignores_views_outside_allow_list():
    targets = [{"view_name": "v_not_allowed", "description": "x"}]
    with (
        patch.object(schema_context.db, "fetch_query_targets", return_value=targets),
        patch.object(
            schema_context.db, "fetch_dictionary", return_value=[]
        ) as mock_dict,
    ):
        schema_context.build_system_prompt()
    # Only allow-listed names are passed to the dictionary lookup.
    assert mock_dict.call_args.args[0] == []


def test_strip_sql_fences():
    assert ollama_client.strip_sql_fences("```sql\nSELECT 1\n```") == "SELECT 1"
    assert ollama_client.strip_sql_fences("SELECT 1") == "SELECT 1"
    assert ollama_client.strip_sql_fences("```\nSELECT 2\n```") == "SELECT 2"
