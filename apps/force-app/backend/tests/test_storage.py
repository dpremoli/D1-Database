"""Storage drive listing — the Google Drive "My Drive" root-detection logic, and the SSD-map
cache (see test_ssd_map_is_cached_between_calls for why that cache exists at all).

The rest of storage.list_drives() enumerates real Windows drive letters via ctypes, which isn't
worth mocking here; _usable_root is the one piece of actual decision logic in the module and is
a pure function over the filesystem.
"""

from __future__ import annotations

import os

from app import storage


def test_prefers_google_drive_my_drive_subfolder(tmp_path):
    root = str(tmp_path) + os.sep
    os.makedirs(os.path.join(root, "My Drive"))

    assert storage._usable_root(root) == os.path.join(root, "My Drive") + os.sep


def test_falls_back_to_the_bare_root_when_there_is_no_my_drive(tmp_path):
    """A normal local/removable drive has no "My Drive" folder — must not be redirected."""
    root = str(tmp_path) + os.sep

    assert storage._usable_root(root) == root


def test_a_plain_file_named_my_drive_does_not_count(tmp_path):
    """Only a real directory should redirect — a same-named file must not be treated as one."""
    root = str(tmp_path) + os.sep
    (tmp_path / "My Drive").write_text("not a folder")

    assert storage._usable_root(root) == root


def test_ssd_map_is_cached_between_calls(monkeypatch):
    """Regression: _detect_ssd_map() shells out to PowerShell + Get-PhysicalDisk (a real CIM/WMI
    query, ~3s measured against real hardware) and list_drives() called it fresh on every single
    request. The General settings tab calls /storage/drives on every mount with no caching of its
    own, so opening it was a guaranteed multi-second stall every time — physical disk media type
    doesn't change while the app is running, so that cost should be paid once, not per view."""
    calls = 0

    def fake_detect():
        nonlocal calls
        calls += 1
        return {"C": True}

    fake_clock = [1000.0]
    monkeypatch.setattr(storage, "_detect_ssd_map", fake_detect)
    monkeypatch.setattr(storage, "_ssd_cache", None, raising=False)
    monkeypatch.setattr(storage, "_ssd_cache_at", 0.0, raising=False)
    monkeypatch.setattr(storage._time, "monotonic", lambda: fake_clock[0])

    assert storage._detect_ssd_map_cached() == {"C": True}
    assert storage._detect_ssd_map_cached() == {"C": True}
    assert calls == 1, "second call within the TTL must reuse the cached map, not re-shell out"

    fake_clock[0] += storage.SSD_CACHE_TTL_SEC + 1
    assert storage._detect_ssd_map_cached() == {"C": True}
    assert calls == 2, "a call past the TTL must refresh — e.g. a newly-attached drive"
