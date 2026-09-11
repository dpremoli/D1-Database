# One-time setup on d1-server: registers a Windows Scheduled Task that polls GitHub every
# 5 minutes for a new force-app-v* release and publishes it automatically
# (auto-publish-release.ps1 -> publish-release.ps1), so a release goes live on the tailnet
# update feed without anyone running a script by hand.
#
# Idempotent: re-running this replaces the existing task definition rather than erroring, so
# it is safe to re-run after e.g. moving the repo or changing $IntervalMinutes.
#
# Prerequisite: `gh auth login` must already work for the Windows account this task runs as
# (the same precondition publish-release.ps1 has always had).
#
# Run once, elevated is NOT required (it only touches this repo's infra/ directory and Task
# Scheduler entries for the current user):
#   powershell -ExecutionPolicy Bypass -File .\install-auto-publish-task.ps1

param(
    [int]$IntervalMinutes = 5
)
$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
$ScriptPath = Join-Path $ScriptDir 'auto-publish-release.ps1'
$TaskName = 'force-app-auto-publish-release'

if (-not (Test-Path $ScriptPath)) {
    throw "auto-publish-release.ps1 not found next to this script at $ScriptPath"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
# IgnoreNew: a slow gh download must not stack a second poll on top of one already running.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Force -Description 'Polls GitHub every few minutes for a new force-app-v* release and publishes it to the Tailscale-only electron-updater feed. See apps/force-app/desktop/scripts/auto-publish-release.ps1.' `
    | Out-Null

Write-Host "Installed scheduled task '$TaskName', polling every $IntervalMinutes minute(s)."
Write-Host "Running it once now to publish whatever release is already current..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5
Write-Host "Log: $(Join-Path (Get-Item $ScriptDir).Parent.Parent.Parent.Parent.FullName 'infra\force-app-updates\auto-publish.log')"
