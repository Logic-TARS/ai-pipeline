param(
    [switch]$SkipPublish
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvExe = 'C:\Users\Family\.local\bin\uv.exe'
$logDir = Join-Path $projectRoot 'output\scheduler'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("ai-briefing-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

$publishArg = if ($SkipPublish) { '--skip-publish' } else { '--publish' }

Push-Location $projectRoot
try {
    & $uvExe run python -m content_pipeline.ai_briefing_runner --date auto $publishArg --handoff-wait-seconds 600 2>&1 |
        Tee-Object -FilePath $logPath -Append
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
