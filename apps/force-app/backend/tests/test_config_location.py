"""Where the backend keeps its own settings, and what happens when it cannot write them.

Regression cover for a packaged-install bug: storage_config.json used to live inside the package,
which under PyInstaller resolves into the install directory (Program Files by default). Writing
there fails for a standard user, and POST /storage/config swallowed the error — so choosing a
capture drive appeared to work, applied to the running process, and then silently reverted on the
next launch.
"""

from __future__ import annotations

import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_main(monkeypatch):
    """Leave app.main as we found it.

    Every test here reloads the module with redirected paths, so it must be reloaded again
    afterwards against the real environment or later tests inherit the redirection. undo() has to
    come first: reloading re-runs module-level makedirs, which the unwritable-dir tests have
    patched to raise.
    """
    yield
    monkeypatch.undo()
    import app.main as main

    importlib.reload(main)


def _fresh_main(monkeypatch, config_dir: str, captures_default: str):
    """Re-import app.main with the config location redirected.

    The paths are module-level constants resolved at import, so a monkeypatched env var only takes
    effect on a reload — which is also what makes this a faithful test of startup behaviour.
    """
    monkeypatch.setenv("FORCE_APP_CONFIG_DIR", config_dir)
    monkeypatch.setenv("FORCE_APP_CAPTURES", captures_default)
    monkeypatch.setenv("FORCE_APP_LOG_DIR", os.path.join(config_dir, "logs"))
    import app.main as main

    return importlib.reload(main)


def test_config_lives_outside_the_package_by_default(monkeypatch, tmp_path):
    """The default must be a per-user writable dir, never package-relative."""
    monkeypatch.delenv("FORCE_APP_CONFIG_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData"))
    import app.main as main

    m = importlib.reload(main)
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))
    assert not m.STORAGE_CONFIG_PATH.startswith(
        pkg_dir
    ), "settings must not live inside the package — that is Program Files once installed"
    assert "force-app" in m.STORAGE_CONFIG_PATH


def test_reads_the_current_location(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    target = tmp_path / "D-drive-captures"
    target.mkdir()
    (cfg_dir / "storage_config.json").write_text(json.dumps({"captures_root": str(target)}))

    m = _fresh_main(monkeypatch, str(cfg_dir), str(tmp_path / "fallback"))
    assert m.CAPTURES_ROOT == str(target)


def test_falls_back_to_the_legacy_location(monkeypatch, tmp_path):
    """An existing install keeps its configured drive after the settings move."""
    cfg_dir = tmp_path / "cfg"  # new location, deliberately empty
    cfg_dir.mkdir()
    target = tmp_path / "legacy-configured-drive"
    target.mkdir()

    m = _fresh_main(monkeypatch, str(cfg_dir), str(tmp_path / "fallback"))
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "storage_config.json").write_text(json.dumps({"captures_root": str(target)}))
    monkeypatch.setattr(m, "LEGACY_STORAGE_CONFIG_PATH", str(legacy / "storage_config.json"))

    assert m._load_captures_root() == str(target)


def test_current_location_wins_over_legacy(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    new_target = tmp_path / "new"
    new_target.mkdir()
    old_target = tmp_path / "old"
    old_target.mkdir()
    (cfg_dir / "storage_config.json").write_text(json.dumps({"captures_root": str(new_target)}))

    m = _fresh_main(monkeypatch, str(cfg_dir), str(tmp_path / "fallback"))
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "storage_config.json").write_text(json.dumps({"captures_root": str(old_target)}))
    monkeypatch.setattr(m, "LEGACY_STORAGE_CONFIG_PATH", str(legacy / "storage_config.json"))

    assert m._load_captures_root() == str(new_target)


def test_setting_a_drive_persists_it(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "cfg"
    m = _fresh_main(monkeypatch, str(cfg_dir), str(tmp_path / "fallback"))
    target = tmp_path / "chosen"
    with TestClient(m.app) as c:
        body = c.post("/storage/config", json={"captures_root": str(target)}).json()

    assert body["persisted"] is True and body["warning"] is None
    saved = json.loads((cfg_dir / "storage_config.json").read_text())
    assert saved["captures_root"] == str(target)
    # ...and it is what a restart would pick up.
    assert m._load_captures_root() == str(target)


def test_unwritable_config_reports_instead_of_silently_reverting(monkeypatch, tmp_path):
    """The actual bug: the drive applies, the save fails, and nobody is told."""
    cfg_dir = tmp_path / "cfg"
    m = _fresh_main(monkeypatch, str(cfg_dir), str(tmp_path / "fallback"))
    target = tmp_path / "chosen"

    def _boom(*a, **kw):
        raise OSError(13, "Access is denied")

    monkeypatch.setattr(m.os, "makedirs", _boom)
    with TestClient(m.app) as c:
        res = c.post("/storage/config", json={"captures_root": str(target)})

    # Not a 500: the request did what it could, and says what it could not do.
    assert res.status_code == 400  # makedirs of the target itself fails first
    assert "cannot create directory" in res.json()["detail"]


def test_unwritable_settings_dir_still_applies_the_drive(monkeypatch, tmp_path):
    """Target creatable, settings dir not: apply for this session, warn that it will not stick."""
    cfg_dir = tmp_path / "cfg"
    m = _fresh_main(monkeypatch, str(cfg_dir), str(tmp_path / "fallback"))
    target = tmp_path / "chosen"
    real_makedirs = m.os.makedirs

    def _selective(path, *a, **kw):
        if str(path).startswith(str(cfg_dir)):
            raise OSError(13, "Access is denied")
        return real_makedirs(path, *a, **kw)

    monkeypatch.setattr(m.os, "makedirs", _selective)
    with TestClient(m.app) as c:
        body = c.post("/storage/config", json={"captures_root": str(target)}).json()

    assert body["captures_root"] == str(target)  # applied now
    assert body["persisted"] is False  # but will not survive a restart
    assert "revert" in body["warning"]


def test_backup_config_falls_back_to_the_legacy_location(monkeypatch, tmp_path):
    from app import backup as bmod

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "backup_config.json").write_text(
        json.dumps({"enabled": True, "server_url": "http://legacy:8210"})
    )

    monkeypatch.setattr(bmod, "BACKUP_CONFIG_PATH", str(cfg_dir / "backup_config.json"))
    monkeypatch.setattr(bmod, "LEGACY_BACKUP_CONFIG_PATH", str(legacy_dir / "backup_config.json"))

    # Losing this silently would turn backup off without saying so — the exact failure the
    # config move must not cause.
    cfg = bmod.load_config(str(tmp_path / "captures"))
    assert cfg["enabled"] is True
    assert cfg["server_url"] == "http://legacy:8210"


def test_backup_config_prefers_the_current_location(monkeypatch, tmp_path):
    from app import backup as bmod

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (cfg_dir / "backup_config.json").write_text(json.dumps({"server_url": "http://new:8210"}))
    (legacy_dir / "backup_config.json").write_text(json.dumps({"server_url": "http://legacy:8210"}))

    monkeypatch.setattr(bmod, "BACKUP_CONFIG_PATH", str(cfg_dir / "backup_config.json"))
    monkeypatch.setattr(bmod, "LEGACY_BACKUP_CONFIG_PATH", str(legacy_dir / "backup_config.json"))

    assert bmod.load_config(str(tmp_path / "captures"))["server_url"] == "http://new:8210"


def test_default_captures_root_is_never_inside_the_package(monkeypatch, tmp_path):
    """A fresh install must not default to storing recordings in the application directory.

    An update replaces that directory, so a user who never picked a drive in Settings would lose
    every recording the first time the app auto-updated — and recordings are the one thing here
    that cannot be regenerated.
    """
    monkeypatch.delenv("FORCE_APP_CAPTURES", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData"))
    import app.main as main

    m = importlib.reload(main)
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))
    root = m._load_captures_root()

    assert not root.startswith(pkg_dir), (
        f"default captures root {root} is inside the package — an update would delete it"
    )
    assert "force-app" in root


def test_force_app_captures_env_is_the_default_not_an_override(monkeypatch, tmp_path):
    """FORCE_APP_CAPTURES supplies the fallback; a saved choice still wins.

    Both halves matter: with nothing stored the env var decides, and with something stored the
    user's own choice is not silently overridden by the environment.
    """
    target = tmp_path / "chosen-by-env"
    monkeypatch.setenv("FORCE_APP_CAPTURES", str(target))
    monkeypatch.setenv("FORCE_APP_CONFIG_DIR", str(tmp_path / "cfg"))
    import app.main as main

    m = importlib.reload(main)
    # Neutralise the real repo's legacy config, which would otherwise be found and (correctly) win.
    monkeypatch.setattr(m, "LEGACY_STORAGE_CONFIG_PATH", str(tmp_path / "nonexistent.json"))
    assert m._load_captures_root() == str(target)

    saved = tmp_path / "saved-by-user"
    saved.mkdir()
    os.makedirs(tmp_path / "cfg", exist_ok=True)
    with open(m.STORAGE_CONFIG_PATH, "w") as f:
        json.dump({"captures_root": str(saved)}, f)
    assert m._load_captures_root() == str(saved)
