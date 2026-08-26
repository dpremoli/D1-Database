"""Storage drive listing — currently just the Google Drive "My Drive" root-detection logic.

The rest of storage.list_drives() enumerates real Windows drive letters via ctypes and shells out
to PowerShell for SSD detection, which isn't worth mocking here; _usable_root is the one piece of
actual decision logic in the module and is a pure function over the filesystem.
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
