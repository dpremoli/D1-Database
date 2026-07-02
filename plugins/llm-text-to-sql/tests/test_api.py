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


def test_chat_runs_safe_sql_and_returns_chart():
    """/api/chat guards the SQL, runs it, and returns a validated chart spec."""
    from app.api import app

    client = app.test_client()
    fake_rows = [
        {"material": "Al", "sample_count": 12},
        {"material": "Ti", "sample_count": 5},
    ]
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="SELECT material, sample_count FROM v_complete_sample_history",
        ),
        patch("app.api.db.run_select", return_value=fake_rows) as mock_run,
        patch(
            "app.api.ollama_client.suggest_chart",
            return_value={"type": "bar", "x": "material", "y": ["sample_count"]},
        ),
    ):
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "samples per material"}]},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["columns"] == ["material", "sample_count"]
    assert body["rows"] == fake_rows
    assert body["chart"] == {"type": "bar", "x": "material", "y": ["sample_count"]}
    assert "LIMIT" in mock_run.call_args.args[0]  # executed the guarded form


def test_chat_forwards_conversation_history():
    """Prior turns are passed to the model so a follow-up has context."""
    from app.api import app

    client = app.test_client()
    history = [
        {"role": "user", "content": "samples per material"},
        {"role": "assistant", "content": "SELECT ..."},
        {"role": "user", "content": "now only aluminium"},
    ]
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="SELECT material FROM v_complete_sample_history",
        ) as mock_gen,
        patch("app.api.db.run_select", return_value=[]),
        patch("app.api.ollama_client.suggest_chart", return_value=None),
    ):
        resp = client.post("/api/chat", json={"messages": history})

    assert resp.status_code == 200
    # The full history (not just the last message) reached the generator.
    passed_messages = mock_gen.call_args.args[1]
    assert passed_messages == history


def test_chat_rejects_unsafe_sql_without_running():
    """Unsafe SQL from the model -> 422, and neither the query nor a chart runs."""
    from app.api import app

    client = app.test_client()
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="DROP TABLE physical_samples;",
        ),
        patch("app.api.db.run_select") as mock_run,
        patch("app.api.ollama_client.suggest_chart") as mock_chart,
    ):
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "drop it"}]},
        )

    assert resp.status_code == 422
    mock_run.assert_not_called()
    mock_chart.assert_not_called()


def test_chat_query_execution_error_returns_422_not_500():
    """A hallucinated column (guard passes, Postgres rejects) -> 422, not 500."""
    from app.api import app
    from app.lib.db import QueryExecutionError

    client = app.test_client()
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="SELECT bogus FROM v_complete_sample_history",
        ),
        patch(
            "app.api.db.run_select",
            side_effect=QueryExecutionError('column "bogus" does not exist'),
        ),
        patch("app.api.ollama_client.suggest_chart") as mock_chart,
    ):
        resp = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "x"}]}
        )

    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "the generated query could not run"
    assert "bogus" in body["reason"]
    mock_chart.assert_not_called()  # never reached charting


def test_chat_falls_back_to_default_chart_when_model_declines():
    """When suggest_chart returns None, an explicit chart request still charts."""
    from app.api import app

    client = app.test_client()
    fake_rows = [{"material_name": "Ti-64", "count": 59}, {"material_name": "Al", "count": 3}]
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="SELECT material_name, count FROM v_complete_sample_history",
        ),
        patch("app.api.db.run_select", return_value=fake_rows),
        patch("app.api.ollama_client.suggest_chart", return_value=None),
    ):
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "make a pie chart"}]},
        )

    assert resp.status_code == 200
    chart = resp.get_json()["chart"]
    assert chart is not None
    assert chart["type"] == "pie"  # honoured the request via the fallback


def test_chat_self_corrects_after_query_error():
    """First SQL hits a missing column; the retry (error fed back) succeeds."""
    from app.api import app
    from app.lib.db import QueryExecutionError

    client = app.test_client()
    good_rows = [{"method_name": "Turning", "n": 117}]
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            side_effect=[
                # bad: method_name is not on the base table
                "SELECT method_name FROM manufacturing_operations",
                # corrected: use the view that has method_name
                "SELECT method_name, count(*) AS n "
                "FROM v_manufacturing_operations_full GROUP BY method_name",
            ],
        ) as mock_gen,
        patch(
            "app.api.db.run_select",
            side_effect=[
                QueryExecutionError('column "method_name" does not exist'),
                good_rows,
            ],
        ),
        patch("app.api.ollama_client.suggest_chart", return_value=None),
    ):
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "most common operation type"}]},
        )

    assert resp.status_code == 200
    assert resp.get_json()["rows"] == good_rows
    assert mock_gen.call_count == 2  # retried once with the error fed back


def test_chat_gives_up_after_max_attempts():
    """Persistent failure returns a graceful 422, not an endless loop."""
    from app.api import app
    from app.lib.db import QueryExecutionError

    client = app.test_client()
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="SELECT bogus FROM manufacturing_operations",
        ) as mock_gen,
        patch(
            "app.api.db.run_select",
            side_effect=QueryExecutionError('column "bogus" does not exist'),
        ),
    ):
        resp = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "x"}]}
        )

    assert resp.status_code == 422
    assert "bogus" in resp.get_json()["reason"]
    assert mock_gen.call_count == 3  # bounded, not infinite


def test_chat_greeting_returns_reply_without_table_or_error():
    """A greeting -> the model's table-free note becomes a plain reply, not a 422."""
    from app.api import app

    client = app.test_client()
    with (
        patch("app.api.schema_context.build_system_prompt", return_value="prompt"),
        patch(
            "app.api.ollama_client.generate_sql_chat",
            return_value="SELECT 'Hi! Ask me about your lab data.' AS note;",
        ),
        patch("app.api.db.run_select") as mock_run,
        patch("app.api.ollama_client.suggest_chart") as mock_chart,
    ):
        resp = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["reply"] == "Hi! Ask me about your lab data."
    assert body["rows"] == []
    assert body["chart"] is None
    mock_run.assert_not_called()  # no query ran
    mock_chart.assert_not_called()  # no chart attempted


def test_chat_requires_a_user_message():
    from app.api import app

    client = app.test_client()
    assert client.post("/api/chat", json={}).status_code == 400
    assert client.post("/api/chat", json={"messages": []}).status_code == 400
    # Only an assistant turn, no user question -> 400.
    resp = client.post(
        "/api/chat", json={"messages": [{"role": "assistant", "content": "hi"}]}
    )
    assert resp.status_code == 400
