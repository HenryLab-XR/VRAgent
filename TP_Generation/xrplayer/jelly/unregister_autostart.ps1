param([string]$TaskName = "XRPlayer_Jelly_Autostart")

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Task '$TaskName' not found."
    exit 0
}
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Task '$TaskName' removed."
$check = netstat -ano | Select-String ":2000.*LISTENING"
if ($check) { Write-Host "[WARN] Port 2000 still in use. Kill manually." }
else         { Write-Host "[OK] Port 2000 is free." }
