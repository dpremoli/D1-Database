# Removes the auto-start scheduled task installed by install_autostart.ps1. Does not stop an
# already-running backend - run stop_recorder.ps1 for that.

$TaskName = "ForceAppRecorderBackend"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Scheduled task '$TaskName' is not installed."
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task '$TaskName'. The backend will no longer auto-start at logon."
