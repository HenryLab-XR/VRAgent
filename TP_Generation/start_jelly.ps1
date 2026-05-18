<#
.SYNOPSIS
    Start the Jelly dashboard server in the background (survives terminal close).
    PID is saved to .jelly.pid so stop_jelly.ps1 can terminate it.
.USAGE
    .\start_jelly.ps1
    .\start_jelly.ps1 -Port 2000 -Python "<repo>\.venv\Scripts\python.exe"
#>
param(
    [int]$Port    = 2000,
    [string]$Python = ""
)

$ScriptDir = $PSScriptRoot
$PidFile   = Join-Path $ScriptDir ".jelly.pid"
$LogFile   = Join-Path $ScriptDir ".jelly.log"
# Server is a package; must be launched with -m, not directly as a script

function Resolve-JellyPython {
    param(
        [string]$Requested,
        [string]$TpGenerationDir
    )

    $workspaceRoot = Split-Path -Parent $TpGenerationDir
    $candidates = @(
        $Requested,
        $env:XRPLAYER_JELLY_PYTHON,
        (Join-Path $workspaceRoot ".venv\Scripts\python.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return $pythonCmd.Source
    }

    throw "[jelly] No usable Python interpreter found. Create .venv first or set -Python / XRPLAYER_JELLY_PYTHON."
}

$Python = Resolve-JellyPython -Requested $Python -TpGenerationDir $ScriptDir
Write-Host "[jelly] Using Python: $Python" -ForegroundColor DarkGray

# Check if already running
if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    $running = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "[jelly] Already running (PID $oldPid) at http://127.0.0.1:$Port/" -ForegroundColor Yellow
        return
    }
}

# Check if port is already in use
$inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    Write-Host "[jelly] Port $Port is already in use by PID $($inUse.OwningProcess)" -ForegroundColor Yellow
    $inUse.OwningProcess | Set-Content $PidFile
    Write-Host "[jelly] Dashboard: http://127.0.0.1:$Port/" -ForegroundColor Cyan
    return
}

# Start-Process creates a truly independent (detached) process that
# survives after the parent PowerShell terminal is closed.
$proc = Start-Process -FilePath $Python `
    -ArgumentList "-u -m xrplayer.jelly --results-dir `"$ScriptDir`" --port $Port" `
    -WorkingDirectory $ScriptDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError  "$LogFile.err" `
    -PassThru

$proc.Id | Set-Content $PidFile
Write-Host "[jelly] Started (PID $($proc.Id)) at http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host "[jelly] To stop: .\stop_jelly.ps1" -ForegroundColor Gray
