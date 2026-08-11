# PyInstaller spec for the frozen recorder backend. One-folder mode (not --onefile): a one-file
# build re-extracts ~200 MB of scipy/numpy to a temp dir on every launch, which is slow and a
# reliable antivirus trigger — see
# docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md.
#
# Build with: pyinstaller force-app-backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_submodules

# "app" must be an explicit hidden import: run_frozen.py hands uvicorn the string "app.main:app"
# rather than importing the module directly, so PyInstaller's static analysis (which only traces
# imports actually executed in run_frozen.py) never discovers the app package on its own and
# leaves it out of the bundle, producing "ModuleNotFoundError: No module named 'app'" at runtime.
hidden_imports = collect_submodules("uvicorn") + collect_submodules("scipy") + collect_submodules("app")

# nidaqmx is only installed on the acquisition machine (`pip install -e ".[nidaq]"`); don't force
# it as a hidden import on a build machine that doesn't have it.
try:
    import nidaqmx  # noqa: F401

    hidden_imports.append("nidaqmx")
except ImportError:
    pass

a = Analysis(
    ["run_frozen.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="force-app-backend",
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="force-app-backend",
)
