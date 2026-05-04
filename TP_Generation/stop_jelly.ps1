<#
.SYNOPSIS
    Stop the Jelly dashboard server started by start_jelly.ps1.
#>
param([int]$Port = 2000)

$ScriptDir = $PSScriptRoot
$PidFile   = Join-Path $ScriptDir ".jelly.pid"

$stopped = $false

# Try PID file first
if (Test-Path $PidFile) {
    $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $savedPid -Force
        Write-Host "[jelly] Stopped PID $savedPid" -ForegroundColor Green
        $stopped = $true
    }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

# Fallback: find by port
if (-not $stopped) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "[jelly] Stopped process on port $Port (PID $($conn.OwningProcess))" -ForegroundColor Green
    } else {
        Write-Host "[jelly] Nothing running on port $Port" -ForegroundColor Yellow
    }
}
