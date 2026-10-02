param(
    [switch]$SkipPublish
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_daily_ai_briefing.ps1'
$taskName = 'AI_Pipeline_Daily_AI_Briefing'
$powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$skipArg = if ($SkipPublish) { ' -SkipPublish' } else { '' }
$arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`"$skipArg"
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '09:30'
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

$description = if ($SkipPublish) {
    'Generate the daily AI briefing through AI Pipeline without publishing.'
} else {
    'Generate and privately publish the daily AI briefing through AI Pipeline.'
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description `
    -Force | Out-Null

Get-ScheduledTask -TaskName $taskName
