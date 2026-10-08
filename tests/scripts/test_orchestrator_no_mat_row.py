"""#190: a Force App cut over the recorder's .mat size limit is saved as a machining_force_analysis
row with directus_files_id NULL. The daemon must treat one that lands in the queue as a clear,
recorded error, not run MATLAB on a missing path or die on `None.replace`."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

pytest.importorskip("psycopg2")
pytest.importorskip("requests")

import force_orchestrator as fo  # noqa: E402


def test_process_file_without_a_linked_mat_is_a_clear_error(tmp_path):
    row = {"id": "r1", "archive_path": None, "fingerprint": None}
    with patch.dict(os.environ, {"FORCE_WORKDIR": str(tmp_path)}), patch.object(fo, "run_matlab") as matlab:
        res = fo.process_file(row, "matlab", 5, {})
    assert res["status"] == "error"
    assert "no archive .mat linked" in res["message"]
    matlab.assert_not_called()
