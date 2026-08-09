"""Shared test fixtures.

The important one here is `isolate_backup_config`: without it, running the suite rewrites the
developer's real backup settings. `backup.BACKUP_CONFIG_PATH` is deliberately an absolute,
drive-independent path in production (so the settings survive changing the recording drive), which
means monkeypatching `main.CAPTURES_ROOT` — what most tests do to sandbox themselves — no longer
redirects it. Tests that POST to /backup/config would then write the installed config for real, and
later tests reading it would see that leftover state instead of the defaults they assert on.
"""

import pytest

from app import backup as backup_mod


@pytest.fixture(autouse=True)
def isolate_backup_config(tmp_path_factory, monkeypatch):
    """Point the backup config at a per-test temp file, for every test in the suite.

    Autouse and unconditional on purpose: this guards a real file outside the repo tree, so it must
    not depend on individual tests remembering to opt in.
    """
    path = tmp_path_factory.mktemp("backup-config") / "backup_config.json"
    monkeypatch.setattr(backup_mod, "BACKUP_CONFIG_PATH", str(path))
    return path
