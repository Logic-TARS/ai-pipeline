param(
    [string]$TaskName = "AI Popline Desktop Browser Helper"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

[PSCustomObject]@{
    ok = $true
    task_name = $TaskName
    removed = [bool]$existing
} | ConvertTo-Json -Compress
