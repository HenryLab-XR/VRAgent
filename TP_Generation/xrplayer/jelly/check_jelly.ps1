param([string]$TaskName = "XRPlayer_Jelly_Autostart", [int]$Port = 2000)
Write-Host "=== XRPlayer Jelly Status ==="
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "[Task] $TaskName  State=$($task.State)  LastRun=$($info.LastRunTime)  LastResult=$($info.LastTaskResult)"
} else {
    Write-Host "[Task] '$TaskName' not registered."
}
try {
    $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
    Write-Host "[HTTP] Jelly UP -> http://127.0.0.1:$Port/  $($r.Content)"
} catch {
    Write-Host "[HTTP] Jelly DOWN (port $Port not responding)"
}
$LogFile = "D:\--UnityProject\HenryLabXR\VRAgent2.0-PVEO_core\_log\jelly.log"
if (Test-Path $LogFile) {
    Write-Host "[Log ] Last 6 lines of $LogFile :"
    Get-Content $LogFile -Tail 6 | ForEach-Object { Write-Host "       $_" }
}
