<#
    fix-docker-vmplatform.ps1

    Enables the Windows "VirtualMachinePlatform" feature (required by WSL2 / Docker
    Desktop) on a machine where Windows Update is INTENTIONALLY policy-blocked and the
    feature's FoD payload was stripped from the image.

    TWO MODES:

      OFFLINE (recommended -- the online WU fetch times out on this build):
        Download the Windows 11 25H2 ISO, then:
          ...\fix-docker-vmplatform.ps1 -Iso "D:\Win11_25H2.iso"
        Sources the payload from the ISO's install image. No Windows Update, no policy
        change at all.

      ONLINE (no -Iso): briefly + reversibly relaxes the WU policy, fetches the payload
        from Windows Update, then restores your policy. Kept as a fallback.

    Run: from an admin shell, or right-click -> Run with PowerShell (self-elevates).
#>
param(
    [string]$Iso = ''      # path to a Windows 11 25H2 ISO; enables OFFLINE mode
)

# ---- self-elevate ----------------------------------------------------------
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Elevating..." -ForegroundColor Yellow
    $argline = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($Iso) { $argline += " -Iso `"$Iso`"" }
    Start-Process powershell.exe $argline -Verb RunAs
    return
}

$ErrorActionPreference = 'Continue'

function Section($t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }

# ===========================================================================
# OFFLINE MODE -- source the payload from a mounted Windows 11 ISO. No WU.
# ===========================================================================
if ($Iso) {
    Section '0. current state'
    $st = (Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform'").InstallState
    Write-Host "VirtualMachinePlatform InstallState = $st  (1=Enabled 2=Disabled 3=Absent)"
    if ($st -eq 1) { Write-Host "Already enabled. Just reboot & start Docker." -ForegroundColor Green; Read-Host 'Enter to exit'; return }
    if (-not (Test-Path $Iso)) { Write-Host "ISO not found: $Iso" -ForegroundColor Red; Read-Host 'Enter to exit'; return }

    $mountDir = 'C:\_vmp_wim'
    $wimTmp   = 'C:\_vmp_install.wim'
    $mountedIso = $null
    try {
        Section '1. mounting ISO'
        $before = (Get-Volume).DriveLetter
        $mountedIso = Mount-DiskImage -ImagePath $Iso -PassThru
        Start-Sleep 2
        $drive = (Get-DiskImage -ImagePath $Iso | Get-Volume).DriveLetter
        if (-not $drive) { $drive = ((Get-Volume).DriveLetter | Where-Object { $_ -and ($_ -notin $before) })[0] }
        $isoRoot = "${drive}:"
        Write-Host "ISO mounted at $isoRoot"

        $wim = "$isoRoot\sources\install.wim"
        $esd = "$isoRoot\sources\install.esd"
        $srcImage = $null; $isEsd = $false
        if (Test-Path $wim) { $srcImage = $wim } elseif (Test-Path $esd) { $srcImage = $esd; $isEsd = $true }
        if (-not $srcImage) { throw "no install.wim/esd under $isoRoot\sources" }
        Write-Host "install image: $srcImage"

        Section '2. finding the Pro-for-Workstations edition index'
        $info = dism /Get-WimInfo /WimFile:$srcImage
        $info | Select-String 'Index|Name' | ForEach-Object { $_.Line.Trim() }
        $idx = $null; $curIdx = $null
        foreach ($ln in $info) {
            if ($ln -match 'Index\s*:\s*(\d+)') { $curIdx = [int]$Matches[1] }
            if ($ln -match 'Name\s*:\s*.*Workstation') { $idx = $curIdx }
        }
        if (-not $idx) {
            foreach ($ln in $info) { if ($ln -match 'Index\s*:\s*(\d+)') { $curIdx=[int]$Matches[1] }; if ($ln -match 'Name\s*:\s*.*\bPro\b') { $idx=$curIdx } }
        }
        if (-not $idx) { $idx = 1; Write-Host "Could not auto-detect edition; defaulting to index 1" -ForegroundColor Yellow }
        Write-Host "Using index $idx"

        # ESD can't be mounted directly for a feature source -> export to a temp WIM.
        if ($isEsd) {
            Section '2b. exporting ESD -> WIM (a few minutes)'
            if (Test-Path $wimTmp) { Remove-Item $wimTmp -Force }
            dism /Export-Image /SourceImageFile:$srcImage /SourceIndex:$idx /DestinationImageFile:$wimTmp /Compress:fast /CheckIntegrity
            $srcImage = $wimTmp; $idx = 1
        }

        Section '3. mounting the install image (read-only)'
        if (Test-Path $mountDir) { dism /Unmount-Image /MountDir:$mountDir /Discard 2>$null | Out-Null; Remove-Item $mountDir -Recurse -Force -EA SilentlyContinue }
        New-Item -ItemType Directory -Path $mountDir -Force | Out-Null
        dism /Mount-Image /ImageFile:$srcImage /Index:$idx /MountDir:$mountDir /ReadOnly

        Section '4. enabling VirtualMachinePlatform from the image'
        dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart /LimitAccess /Source:"$mountDir\Windows\WinSxS"
        $rc = $LASTEXITCODE
        Write-Host "DISM exit code: $rc"
    }
    catch { Write-Host "OFFLINE mode error: $_" -ForegroundColor Red; $rc = -1 }
    finally {
        Section '5. cleanup'
        dism /Unmount-Image /MountDir:$mountDir /Discard 2>$null | Out-Null
        Remove-Item $mountDir -Recurse -Force -EA SilentlyContinue
        if (Test-Path $wimTmp) { Remove-Item $wimTmp -Force -EA SilentlyContinue }
        if ($mountedIso) { Dismount-DiskImage -ImagePath $Iso | Out-Null; Write-Host "ISO dismounted." }
    }

    Section '6. result'
    $st2 = (Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform'").InstallState
    if ($st2 -eq 1) {
        Write-Host "SUCCESS. VirtualMachinePlatform is enabled." -ForegroundColor Green
        Write-Host "REBOOT, then start Docker Desktop -- your docker_data.vhdx (DB) mounts back intact." -ForegroundColor Yellow
    } else {
        Write-Host "Enable did not complete (state=$st2, code=$rc)." -ForegroundColor Red
        Write-Host "If DISM said 0x800f0906/0x800f081f, the ISO build differs from 26200 -- grab the 25H2 ISO." -ForegroundColor Yellow
    }
    Read-Host "`nEnter to close"
    return
}

# ===========================================================================
# ONLINE MODE (fallback) -- fetch from Windows Update with reversible policy.
# ===========================================================================
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup  = Join-Path ([Environment]::GetFolderPath('Desktop')) "wu-policy-backup-$stamp.reg"
$WUkey   = 'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'
$SVCkey  = 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Servicing'

# ---- 0. show current feature state -----------------------------------------
Section '0. current state'
$st = (Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform'").InstallState
Write-Host "VirtualMachinePlatform InstallState = $st  (1=Enabled 2=Disabled 3=Absent)"
if ($st -eq 1) { Write-Host "Already enabled. Nothing to do -- just reboot & start Docker." -ForegroundColor Green; Read-Host 'Enter to exit'; return }

# ---- 1. back up the policy keys --------------------------------------------
Section '1. backing up WU policy'
reg export $WUkey  $backup /y  2>$null | Out-Null
reg export $SVCkey ($backup -replace '\.reg$','-servicing.reg') /y 2>$null | Out-Null
Write-Host "Backup written: $backup" -ForegroundColor Green

# capture originals so we can restore precisely even if the .reg import is skipped
$AUkey     = "$WUkey\AU"
$origUX    = (Get-ItemProperty "Registry::$WUkey"  -Name SetDisableUXWUAccess -EA SilentlyContinue).SetDisableUXWUAccess
$origUseWU = (Get-ItemProperty "Registry::$SVCkey" -Name UseWindowsUpdate  -EA SilentlyContinue).UseWindowsUpdate
$origNoAU  = (Get-ItemProperty "Registry::$AUkey"  -Name NoAutoUpdate -EA SilentlyContinue).NoAutoUpdate

# ---- 2. temporarily allow FoD from Windows Update --------------------------
Section '2. temporarily FULLY enabling WU for the fetch'
Write-Host "NOTE: Automatic Updates are briefly turned ON so the WU agent will service" -ForegroundColor Yellow
Write-Host "      the on-demand payload request. Nothing installs/reboots on its own;" -ForegroundColor Yellow
Write-Host "      the original policy (incl. NoAutoUpdate=1) is restored at the end." -ForegroundColor Yellow
# allow WU access for the agent...
Set-ItemProperty "Registry::$WUkey" -Name SetDisableUXWUAccess -Value 0 -Type DWord -Force
# ...permit optional-feature payloads from WU (0 = allowed)...
if (-not (Test-Path "Registry::$SVCkey")) { New-Item -Path "Registry::$SVCkey" -Force | Out-Null }
Set-ItemProperty "Registry::$SVCkey" -Name UseWindowsUpdate -Value 0 -Type DWord -Force
# ...and let the AU agent run so DISM's request is serviced (the missing lever).
if (-not (Test-Path "Registry::$AUkey")) { New-Item -Path "Registry::$AUkey" -Force | Out-Null }
Set-ItemProperty "Registry::$AUkey" -Name NoAutoUpdate -Value 0 -Type DWord -Force
gpupdate /target:computer /force 2>$null | Out-Null
Set-Service wuauserv -StartupType Manual -EA SilentlyContinue
Restart-Service wuauserv -EA SilentlyContinue
Start-Sleep 3

# ---- 3. enable the feature online ------------------------------------------
Section '3. enabling VirtualMachinePlatform from Windows Update'
Write-Host "This downloads a small payload; give it up to a couple of minutes..."
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
$rc = $LASTEXITCODE
Write-Host "DISM exit code: $rc"

# ---- 4. restore the original policy (always) -------------------------------
Section '4. restoring your update-blocking policy'
if ($null -eq $origUX) { Remove-ItemProperty "Registry::$WUkey" -Name SetDisableUXWUAccess -EA SilentlyContinue }
else { Set-ItemProperty "Registry::$WUkey" -Name SetDisableUXWUAccess -Value $origUX -Type DWord -Force }
if ($null -eq $origUseWU) { Remove-ItemProperty "Registry::$SVCkey" -Name UseWindowsUpdate -EA SilentlyContinue }
else { Set-ItemProperty "Registry::$SVCkey" -Name UseWindowsUpdate -Value $origUseWU -Type DWord -Force }
if ($null -eq $origNoAU) { Remove-ItemProperty "Registry::$AUkey" -Name NoAutoUpdate -EA SilentlyContinue }
else { Set-ItemProperty "Registry::$AUkey" -Name NoAutoUpdate -Value $origNoAU -Type DWord -Force }
Restart-Service wuauserv -EA SilentlyContinue
gpupdate /target:computer /force 2>$null | Out-Null
Write-Host "Policy restored to pre-run state. Backup kept at:`n  $backup" -ForegroundColor Green

# ---- 5. verdict ------------------------------------------------------------
Section '5. result'
$st2 = (Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform'").InstallState
if ($rc -eq 0 -or $st2 -eq 1) {
    Write-Host "SUCCESS. VirtualMachinePlatform is enabled." -ForegroundColor Green
    Write-Host "REBOOT, then start Docker Desktop. Your docker_data.vhdx (DB) mounts back intact." -ForegroundColor Yellow
} else {
    Write-Host "Enable did not complete (code $rc)." -ForegroundColor Red
    Write-Host "Most likely the WU FoD endpoint was unreachable/slow. Fallback: the ISO /Source route." -ForegroundColor Yellow
    Write-Host "Your update policy has still been restored." -ForegroundColor Green
}
Read-Host "`nEnter to close"
