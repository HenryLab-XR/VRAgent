param([string]$TaskName = "XRPlayer_Jelly_Autostart", [int]$Port = 2000)

function Format-TaskResult {
    param([int]$Code)

    switch ($Code) {
        0 { return "0 (OK)" }
        3221225786 { return "3221225786 (0xC000013A: interrupted or console closed)" }
        default { return [string]$Code }
    }
}

Write-Host "=== XRPlayer Jelly Status ==="
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "[Task] $TaskName  State=$($task.State)  LastRun=$($info.LastRunTime)  LastResult=$(Format-TaskResult $info.LastTaskResult)"
} else {
    Write-Host "[Task] '$TaskName' not registered."
}
try {
    $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
    Write-Host "[HTTP] Jelly UP -> http://127.0.0.1:$Port/  $($r.Content)"
} catch {
    Write-Host "[HTTP] Jelly DOWN (port $Port not responding)"
}
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TpGenerationDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$LogCandidates = @(
    (Join-Path $TpGenerationDir ".jelly.log"),
    (Join-Path $TpGenerationDir ".jelly.log.err")
) | Where-Object { Test-Path $_ }

if ($LogCandidates) {
    $LogFile = $LogCandidates |
        Sort-Object { (Get-Item $_).LastWriteTimeUtc } -Descending |
        Select-Object -First 1
    Write-Host "[Log ] Last 6 lines of $LogFile :"
    Get-Content $LogFile -Tail 6 | ForEach-Object { Write-Host "       $_" }
}
