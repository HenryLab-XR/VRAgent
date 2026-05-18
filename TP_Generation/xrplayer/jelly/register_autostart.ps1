param(
    [string]$TaskName = "XRPlayer_Jelly_Autostart",
    [int]$Port        = 2000
)

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$TpGenerationDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$LauncherPs1 = Join-Path $TpGenerationDir "start_jelly.ps1"
$PowerShellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$LogPath     = Join-Path $TpGenerationDir ".jelly.log"
$LogDir      = Split-Path -Parent $LogPath
$UserId      = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$IsAdmin     = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$workspaceRoot = Split-Path -Parent $TpGenerationDir
$PythonCandidates = @(
  $env:XRPLAYER_JELLY_PYTHON,
  (Join-Path $workspaceRoot ".venv\Scripts\python.exe")
)
$PythonExe = $PythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$TaskArguments = @(
  "-NoProfile",
  "-NonInteractive",
  "-ExecutionPolicy", "Bypass",
  "-WindowStyle", "Hidden",
  "-File", ('"{0}"' -f $LauncherPs1),
  "-Port", $Port
)
if ($PythonExe) {
  $TaskArguments += @("-Python", ('"{0}"' -f $PythonExe))
}
$TaskArgumentsText = $TaskArguments -join " "

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

if ($IsAdmin) {
    Write-Host "[jelly] Admin mode -> AtStartup (SYSTEM)"
    $TriggerXml = "<BootTrigger><Enabled>true</Enabled></BootTrigger>"
    $PrincipalXml = "<Principal id='Author'><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal>"
} else {
    Write-Host "[jelly] Non-admin mode -> AtLogon (current user: $UserId)"
    Write-Host "        Re-run as Administrator to change to boot-time (SYSTEM) autostart."
    $TriggerXml = "<LogonTrigger><UserId>$UserId</UserId><Enabled>true</Enabled></LogonTrigger>"
    $PrincipalXml = "<Principal id='Author'><UserId>$UserId</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>"
}

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>XRPlayer Jelly Dashboard autostart</Description></RegistrationInfo>
  <Triggers>$TriggerXml</Triggers>
  <Principals>$PrincipalXml</Principals>
  <Settings>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RestartOnFailure><Interval>PT2M</Interval><Count>5</Count></RestartOnFailure>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$PowerShellExe</Command>
      <Arguments>$TaskArgumentsText</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$xmlPath = [System.IO.Path]::GetTempFileName() + ".xml"
[System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)
schtasks /create /tn $TaskName /xml "$xmlPath" /f 2>&1
Remove-Item $xmlPath -ErrorAction SilentlyContinue

Write-Host "[OK] Task '$TaskName' registered."

schtasks /run /tn $TaskName 2>&1
Start-Sleep -Seconds 4

try {
    $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "[OK] Jelly is up: $($r.Content)"
} catch {
    Write-Host "[WARN] Jelly not responding yet. Check log: $LogPath"
}

Write-Host "---"
Write-Host "Dashboard : http://127.0.0.1:$Port/"
Write-Host "Log       : $LogPath"
Write-Host "Uninstall : .\unregister_autostart.ps1"
Write-Host "Status    : .\check_jelly.ps1"
