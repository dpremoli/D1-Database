"""The release workflow's Windows dry run runs on a PR only when the PR can break the packaged app
(.github/scripts/release_plan.py pr_build_reasons / pr_packaging_changes)."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "release_plan", ROOT / ".github/scripts/release_plan.py"
)
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

PKG = {
    "version": "0.1.34",
    "main": "dist/main.js",
    "scripts": {"build": "tsc"},
    "dependencies": {"electron-updater": "^6.3.0"},
    "devDependencies": {
        "electron": "^43.3.0",
        "typescript": "^5.7.3",
        "vitest": "^4.1.10",
    },
}
LOCK = {
    "packages": {
        "apps/force-app/desktop": {"version": "0.1.34"},
        "node_modules/electron": {"version": "43.3.0"},
        "node_modules/vue": {"version": "3.5.24"},
    }
}


def bump(d: dict, path: list[str], value) -> dict:
    out = json.loads(json.dumps(d))
    node = out
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    return out


def reasons(changed, new_pkg=PKG, new_lock=LOCK):
    return rp.pr_build_reasons(changed, PKG, new_pkg, LOCK, new_lock)


def test_unrelated_change_needs_no_windows_build():
    assert reasons(["apps/force-app/web/src/x.ts", "docs/ci-cd.md"]) == []


def test_dev_dependency_bump_that_does_not_touch_packaging_tools_is_skipped():
    pkg = bump(PKG, ["devDependencies", "typescript"], "^7.0.2")
    lock = bump(LOCK, ["packages", "node_modules/vue"], {"version": "3.5.43"})
    assert reasons([rp.DESKTOP_PKG, rp.LOCKFILE], pkg, lock) == []


@pytest.mark.parametrize(
    "path,value",
    [
        (["version"], "0.1.35"),
        (["main"], "dist/other.js"),
        (["dependencies", "electron-updater"], "^6.4.0"),
        (["devDependencies", "electron"], "^44.5.1"),
        (["devDependencies", "electron-builder"], "^26.0.0"),
    ],
)
def test_version_entry_point_runtime_deps_and_packaging_tools_build(path, value):
    assert reasons([rp.DESKTOP_PKG], bump(PKG, path, value)) != []


def test_a_lockfile_only_electron_bump_builds():
    lock = bump(LOCK, ["packages", "node_modules/electron"], {"version": "43.4.0"})
    assert reasons([rp.LOCKFILE], new_lock=lock) == [
        "node_modules/electron in package-lock.json"
    ]


@pytest.mark.parametrize("path", rp.PACKAGING_FILES)
def test_packaging_files_build(path):
    assert reasons([path]) == [path]


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_pr_packaging_changes_diffs_the_merge_commit_against_its_base(
    tmp_path, monkeypatch
):
    for d in ("apps/force-app/desktop",):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / rp.DESKTOP_PKG).write_text(json.dumps(PKG))
    (tmp_path / rp.LOCKFILE).write_text(json.dumps(LOCK))
    for k in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{k}_NAME", "t")
        monkeypatch.setenv(f"{k}_EMAIL", "t@t")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)

    (tmp_path / rp.LOCKFILE).write_text(
        json.dumps(bump(LOCK, ["packages", "node_modules/vue"], {"version": "3.5.43"}))
    )
    git(tmp_path, "commit", "-qam", "dependabot: bump vue")
    assert rp.pr_packaging_changes() == []

    (tmp_path / rp.DESKTOP_PKG).write_text(json.dumps(bump(PKG, ["version"], "0.1.35")))
    git(tmp_path, "commit", "-qam", "release 0.1.35")
    assert rp.pr_packaging_changes() == [f"{rp.DESKTOP_PKG} version"]


def test_without_a_base_commit_it_builds_to_be_safe(tmp_path, monkeypatch):
    (tmp_path / "apps/force-app/desktop").mkdir(parents=True)
    (tmp_path / rp.DESKTOP_PKG).write_text(json.dumps(PKG))
    monkeypatch.chdir(tmp_path)
    assert rp.pr_packaging_changes() != []
