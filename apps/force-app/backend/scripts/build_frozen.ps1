# Freezes the recorder backend into a one-folder PyInstaller bundle at
# apps\force-app\backend\dist\force-app-backend\. Run from the backend's own venv so the frozen
# build picks up whatever is installed there (including the nidaqmx extra, if the venv has it).
#
# Run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_frozen.ps1

$ErrorActionPreference = 'Stop'
$BackendDir = Split-Path -Parent $PSScriptRoot
Push-Location $BackendDir
try {
    if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
        Write-Host "pyinstaller not found on PATH - installing the [build] extra..."
        pip install -e ".[build]"
    }
    pyinstaller force-app-backend.spec --noconfirm
    Write-Host "Built: $BackendDir\dist\force-app-backend\force-app-backend.exe"
} finally {
    Pop-Location
}
