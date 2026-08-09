# Stops the recorder backend if it is running on port 8200. Use this instead of hunting for the
# python.exe process in Task Manager.

$Port = 8200
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $conn) {
    Write-Host "Recorder backend is not running on port $Port."
    exit 0
}
Write-Host "Stopping recorder backend (PID $($conn.OwningProcess))..."
Stop-Process -Id $conn.OwningProcess -Force
