# One-time setup: registers a Scheduled Task that starts the recorder backend automatically at
# logon, and re-checks every 5 minutes afterward (start_recorder.ps1 is a no-op if it's already
# running) so a crashed backend gets relaunched without you noticing. Runs as your own user - no
# admin rights required.
#
# Run once:
#   powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1

$TaskName = "ForceAppRecorderBackend"
$ScriptPath = Join-Path $PSScriptRoot "start_recorder.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

$atLogon = New-ScheduledTaskTrigger -AtLogOn
$everyFewMin = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger @($atLogon, $everyFewMin) -Settings $settings `
    -Description "Auto-starts the force-app NI-DAQ/LabAmp recording backend (uvicorn, port 8200) at logon and keeps it running." `
    | Out-Null

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
Write-Host "Done. Check logs at $(Join-Path (Split-Path -Parent $PSScriptRoot) 'logs') if the Record page still can't reach the backend."
Write-Host "To remove this later: powershell -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1"
