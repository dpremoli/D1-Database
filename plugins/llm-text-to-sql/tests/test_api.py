"""API smoke tests — health, plus the /api/ask guard path with Ollama and the
database mocked, so no running stack is required."""

from unittest.mock import patch


def test_health_endpoint():
    from app.api import app

    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_ask_rejects_unsafe_llm_sql():
    """If the model returns DML, /api/ask must reject it with 422 and not run it."""
    from app.api import app

    client = app.test_client()
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql",
            return_value="DROP TABLE physical_samples;",
        ),
        patch("app.api.db.run_select") as mock_run,
    ):
        resp = client.post("/api/ask", json={"question": "delete everything"})

    assert resp.status_code == 422
    mock_run.assert_not_called()


def test_ask_runs_safe_llm_sql():
    """A valid SELECT is guarded and executed; rows are returned."""
    from app.api import app

    client = app.test_client()
    fake_rows = [{"sample_code": "10-AA-MF", "mass_grams": 12.5}]
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql",
            return_value="```sql\nSELECT sample_code, mass_grams "
            "FROM v_complete_sample_history\n```",
        ),
        patch("app.api.db.run_select", return_value=fake_rows) as mock_run,
    ):
        resp = client.post("/api/ask", json={"question": "list samples"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["columns"] == ["sample_code", "mass_grams"]
    assert body["rows"] == fake_rows
    # The executed SQL must be the guarded (LIMIT-wrapped) form.
    executed = mock_run.call_args.args[0]
    assert "LIMIT" in executed


def test_ask_requires_question():
    from app.api import app

    client = app.test_client()
    resp = client.post("/api/ask", json={})
    assert resp.status_code == 400
