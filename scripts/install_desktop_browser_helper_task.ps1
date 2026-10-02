param(
    [string]$TaskName = "AI Pipeline Desktop Browser Helper",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8767,
    [string]$PythonExe = "",
    [string]$UserId = "",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

if (-not $PythonExe) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $PythonExe = $pythonCommand.Source
}

if (-not $UserId) {
    $UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

$helperCommand = @(
    "Set-Location -LiteralPath '$($projectRoot.Replace("'", "''"))'"
    "& '$($PythonExe.Replace("'", "''"))' -m content_pipeline.diagnostics desktop-helper --host $HostAddress --port $Port"
) -join "; "

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$helperCommand`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal `
    -UserId $UserId `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Runs AI Pipeline's localhost desktop browser helper in the logged-in Windows desktop session." `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}

$task = Get-ScheduledTask -TaskName $TaskName
[PSCustomObject]@{
    ok = $true
    task_name = $TaskName
    state = $task.State.ToString()
    project_root = $projectRoot
    python = $PythonExe
    user_id = $UserId
    helper_url = "http://$HostAddress`:$Port"
    start_now = [bool]$StartNow
    opens_browser = $false
} | ConvertTo-Json -Compress
