<#
.SYNOPSIS
    Nightly backup of the D1 production Postgres database on d1-server.

.DESCRIPTION
    Runs pg_dump inside the running Postgres container, copies the archive out
    to a host folder, verifies the copy byte-for-byte by size, and prunes
    archives older than the retention window.

    Two artifacts are produced per run:

      d1_database-<stamp>.dump  custom-format archive of the database itself,
                                restorable with pg_restore (supports selective
                                and parallel restore).
      globals-<stamp>.sql       roles and other cluster-level objects, which a
                                per-database dump does NOT contain. Without
                                this a restore onto a fresh cluster fails on
                                missing role grants.

    The dump is written to the container's /tmp first and copied out with
    `docker cp` rather than streamed to stdout: PowerShell applies text
    encoding to redirected output, which silently corrupts binary streams.

    Credentials are never passed on the command line or logged — the script
    reads POSTGRES_USER / POSTGRES_DB from the container's own environment.

.PARAMETER DestinationRoot
    Folder to write archives to. Defaults to D:\D1-Backups\postgres.

.PARAMETER RetentionDays
    Archives older than this are deleted after a successful run. Defaults to 14.
    Pruning is skipped entirely if the run fails, so a broken backup job never
    eats the last good archives.

.PARAMETER Container
    Name of the Postgres container. Defaults to d1-database-postgres-1.

.EXAMPLE
    pwsh -File scripts\backup-postgres.ps1

.NOTES
    Verify restorability periodically — a dump that has never been restored is
    not a backup. See docs/adr/0010 step 0. To test:

      docker exec <container> sh -c 'psql -U "$POSTGRES_USER" -d postgres \
        -c "CREATE DATABASE restore_test"'
      docker cp <archive> <container>:/tmp/t.dump
      docker exec <container> sh -c 'pg_restore -U "$POSTGRES_USER" \
        -d restore_test -j 2 /tmp/t.dump'

    then compare row counts against production and drop restore_test.
#>
[CmdletBinding()]
param(
    [string]$DestinationRoot = 'D:\D1-Backups\postgres',
    [int]$RetentionDays = 14,
    [string]$Container = 'd1-database-postgres-1'
)

$ErrorActionPreference = 'Stop'

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $DestinationRoot 'backup.log'

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Output $line
    if (Test-Path $DestinationRoot) { Add-Content -Path $logFile -Value $line }
}

# Docker Desktop does not put docker.exe on the PATH of non-interactive
# scheduled tasks, so resolve it explicitly before falling back to the PATH.
function Resolve-Docker {
    $candidate = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    if (Test-Path $candidate) { return $candidate }
    $onPath = (Get-Command docker -ErrorAction SilentlyContinue).Source
    if ($onPath) { return $onPath }
    throw 'docker.exe not found (checked Docker Desktop install path and PATH).'
}

try {
    New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
    $docker = Resolve-Docker
    Write-Log "Backup starting -> $DestinationRoot"

    # Refuse to dump a container that is not running: `docker exec` against a
    # stopped container fails in ways that are easy to mistake for an empty DB.
    $state = & $docker inspect -f '{{.State.Running}}' $Container 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Container '$Container' not found." }
    if ($state.Trim() -ne 'true') { throw "Container '$Container' is not running (State.Running=$state)." }

    # --- database archive -------------------------------------------------
    & $docker exec $Container sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/backup.dump'
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE)." }

    $srcSize = [int64](& $docker exec $Container sh -c 'stat -c %s /tmp/backup.dump').Trim()
    $dumpDest = Join-Path $DestinationRoot "d1_database-$stamp.dump"
    & $docker cp "${Container}:/tmp/backup.dump" $dumpDest
    if ($LASTEXITCODE -ne 0) { throw "docker cp failed (exit $LASTEXITCODE)." }

    $dstSize = (Get-Item $dumpDest).Length
    if ($dstSize -ne $srcSize) {
        throw "Size mismatch: container $srcSize bytes, host $dstSize bytes. Copy is not trustworthy."
    }
    Write-Log ("Database archive OK: {0} ({1:N0} bytes, {2:N1} MB)" -f (Split-Path $dumpDest -Leaf), $dstSize, ($dstSize / 1MB))

    # --- cluster globals (roles) -----------------------------------------
    $globalsDest = Join-Path $DestinationRoot "globals-$stamp.sql"
    & $docker exec $Container sh -c 'pg_dumpall -U "$POSTGRES_USER" --globals-only -f /tmp/globals.sql'
    if ($LASTEXITCODE -ne 0) { throw "pg_dumpall --globals-only failed (exit $LASTEXITCODE)." }
    & $docker cp "${Container}:/tmp/globals.sql" $globalsDest
    if ($LASTEXITCODE -ne 0) { throw "docker cp of globals failed (exit $LASTEXITCODE)." }
    Write-Log ("Globals OK: {0} ({1:N0} bytes)" -f (Split-Path $globalsDest -Leaf), (Get-Item $globalsDest).Length)

    # --- prune (only after a fully successful run) ------------------------
    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    $stale = Get-ChildItem -Path $DestinationRoot -File |
             Where-Object { $_.Name -match '^(d1_database-|globals-)' -and $_.LastWriteTime -lt $cutoff }
    foreach ($f in $stale) {
        Remove-Item $f.FullName -Force
        Write-Log "Pruned $($f.Name)"
    }

    $kept = @(Get-ChildItem -Path $DestinationRoot -Filter 'd1_database-*.dump' -File)
    $totalGb = ($kept | Measure-Object -Property Length -Sum).Sum / 1GB
    Write-Log ("Backup complete. {0} archive(s) retained, {1:N1} GB total." -f $kept.Count, $totalGb)
    exit 0
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    exit 1
}
finally {
    # Always clear the container's /tmp, including on failure — otherwise a
    # 1.3 GB file is left in the container's writable layer after every error.
    if ($docker) {
        & $docker exec $Container sh -c 'rm -f /tmp/backup.dump /tmp/globals.sql' 2>$null | Out-Null
    }
}
