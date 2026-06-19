"""Smoke tests for the plugin template — replace with real tests."""

from unittest.mock import patch


def test_example_job_calls_directus(tmp_path):
    """Verify the stub job calls patch_item with status=processed."""
    fake_file = tmp_path / "sample.bin"
    fake_file.write_bytes(b"\x00" * 64)

    with (
        patch("app.jobs.example_job.minio_client.download_file") as mock_dl,
        patch("app.jobs.example_job.directus_client.patch_item") as mock_patch,
    ):
        mock_dl.side_effect = lambda key, path: fake_file.replace(path)

        from app.jobs.example_job import example_job

        example_job("session-123", "test/sample.bin")

    calls = [c.args for c in mock_patch.call_args_list]
    statuses = [c[2].get("status") for c in calls]
    assert "processed" in statuses


def test_health_endpoint():
    """GET /health returns {status: ok}."""
    from app.webhook import app

    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
