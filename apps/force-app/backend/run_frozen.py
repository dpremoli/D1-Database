"""Entry point for the PyInstaller-frozen backend. The Electron sidecar (apps/force-app/desktop)
spawns the frozen exe with `--port <n>`; this runs uvicorn in-process rather than shelling out to
the `uvicorn` CLI (which isn't present inside a frozen bundle), bound to loopback only — the
sidecar is reached solely by the Electron renderer on the same machine.
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
