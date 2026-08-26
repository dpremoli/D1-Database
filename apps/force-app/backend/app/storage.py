"""Storage enumeration and monitoring — lists available drives with type (SSD/HDD),
free space, and total capacity. Windows-focused (the acquisition PC runs Windows)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess


def _drive_letters() -> list[str]:
    """Return mounted drive letters on Windows (e.g. ['C', 'D', 'E'])."""
    if platform.system() != "Windows":
        return []
    import ctypes

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[union-attr]
    return [chr(65 + i) for i in range(26) if bitmask & (1 << i)]


def _drive_type_win(letter: str) -> str:
    """Return Windows drive type string for a drive letter."""
    import ctypes

    # GetDriveTypeW: 0=unknown, 1=no_root, 2=removable, 3=fixed, 4=network, 5=cdrom, 6=ramdisk
    t = ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\")  # type: ignore[union-attr]
    return {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}.get(t, "unknown")


def _detect_ssd_map() -> dict[str, bool]:
    """Use PowerShell to detect which physical disks are SSD. Returns {drive_letter: is_ssd}."""
    try:
        ps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-Partition | ForEach-Object {"
                    "  $disk = Get-PhysicalDisk -DeviceNumber $_.DiskNumber -ErrorAction SilentlyContinue;"
                    "  [PSCustomObject]@{Letter=$_.DriveLetter; MediaType=if($disk){$disk.MediaType}else{'Unknown'}}"
                    "} | Where-Object { $_.Letter } | ConvertTo-Json -Compress"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if ps.returncode != 0:
            return {}
        import json

        data = json.loads(ps.stdout)
        if isinstance(data, dict):
            data = [data]
        return {
            str(item.get("Letter", "")).upper(): str(item.get("MediaType", "")).upper() == "SSD"
            for item in data
            if item.get("Letter")
        }
    except Exception:
        return {}


def _usable_root(root: str) -> str:
    """Return the path that should actually be offered for a drive, not necessarily its bare root.

    Google Drive for Desktop's virtual drive presents its writable content under
    "<root>My Drive", not the root itself — the root is a synthetic shell namespace (it also
    lists "Other computers"/shared drives there) that silently refuses to create files or folders
    directly: os.makedirs on it fails with WinError 2 ("cannot find the file specified"), not
    even a normal access-denied. "<root>My Drive" is a real, writable path, so use it when present
    rather than offering a drive that 400s the moment it's picked.
    """
    my_drive = os.path.join(root, "My Drive")
    if os.path.isdir(my_drive):
        return my_drive + os.sep
    return root


def list_drives() -> list[dict]:
    """Enumerate available storage drives with capacity information."""
    if platform.system() != "Windows":
        # Linux/macOS fallback: just report root
        try:
            u = shutil.disk_usage("/")
            return [
                {
                    "path": "/",
                    "label": "Root",
                    "type": "fixed",
                    "is_ssd": None,
                    "total_gb": round(u.total / 1e9, 1),
                    "free_gb": round(u.free / 1e9, 1),
                    "used_pct": round((u.total - u.free) / u.total * 100, 1) if u.total else 0,
                }
            ]
        except Exception:
            return []

    letters = _drive_letters()
    ssd_map = _detect_ssd_map()
    drives: list[dict] = []
    for letter in letters:
        root = f"{letter}:\\"
        dtype = _drive_type_win(letter)
        # Network shares and cloud-sync virtual drives (Google Drive et al.) are offered, but
        # flagged — the live backup feature exists specifically because a network hiccup mid-
        # recording is a real risk to an in-progress capture, which local disk doesn't share.
        if dtype not in ("fixed", "removable", "network"):
            continue
        try:
            u = shutil.disk_usage(root)
        except OSError:
            continue
        usable_root = _usable_root(root)
        is_cloud_sync = usable_root != root
        less_reliable = dtype == "network" or is_cloud_sync
        drives.append(
            {
                "path": usable_root,
                "letter": letter,
                "label": _volume_label(root),
                "type": dtype,
                "is_ssd": ssd_map.get(letter),
                "less_reliable": less_reliable,
                "reliability_note": (
                    "Network drive — a connection drop mid-recording can lose or corrupt an "
                    "in-progress capture. Consider Settings > Live Backup instead."
                    if dtype == "network"
                    else "Cloud-sync drive — a sync hiccup mid-recording can lose or corrupt an "
                    "in-progress capture. Consider Settings > Live Backup instead."
                    if is_cloud_sync
                    else None
                ),
                "total_gb": round(u.total / 1e9, 1),
                "free_gb": round(u.free / 1e9, 1),
                "used_pct": round((u.total - u.free) / u.total * 100, 1) if u.total else 0,
            }
        )
    # Sort: reliable drives first (SSD ahead of HDD within that group, then by free space
    # descending), network/cloud-sync drives pushed to the bottom regardless of free space.
    drives.sort(key=lambda d: (d.get("less_reliable", False), not d.get("is_ssd", False), -(d.get("free_gb", 0))))
    return drives


def _volume_label(root: str) -> str:
    """Get Windows volume label for a drive root like 'C:\\'."""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[union-attr]
            root, buf, 256, None, None, None, None, 0
        )
        return buf.value or ""
    except Exception:
        return ""


def disk_usage_for(path: str) -> dict:
    """Return disk usage for the partition containing `path`.

    On failure `free_gb` is None, NOT 0 — the difference matters: a caller that reads a failed stat
    as "0 GB free" concludes the disk is full. `Session._watch_disk` would then force-stop a healthy
    recording over one transient error, which is a real risk now that the captures root can live on
    a removable or network drive. None means "unknown"; callers must decide explicitly.
    """
    try:
        u = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(u.total / 1e9, 1),
            "free_gb": round(u.free / 1e9, 1),
            "used_pct": round((u.total - u.free) / u.total * 100, 1) if u.total else 0,
        }
    except OSError:
        return {"path": path, "total_gb": None, "free_gb": None, "used_pct": None}


# The raw writer is float32 (`d1rw.py` writes dtype "<f4", and recovery.py computes
# row_bytes = n_cols * 4) — 4 bytes per sample, not 8. Assuming float64 doubles every size estimate
# and bandwidth readout, which turns into spurious "not enough disk space" prompts.
RAW_BYTES_PER_SAMPLE = 4


def estimate_recording_size_gb(
    sample_rate: float, duration_sec: float, n_channels: int = 10
) -> float:
    """Estimate recording file size in GB (raw float32 per sample)."""
    return sample_rate * duration_sec * n_channels * RAW_BYTES_PER_SAMPLE / 1e9
