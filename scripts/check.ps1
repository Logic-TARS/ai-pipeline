# AI Pipeline Quality Gate (PowerShell)
# Run before committing: .\scripts\check.ps1

$ErrorActionPreference = "Stop"
$failed = $false
if (-not $env:UV_LINK_MODE) { $env:UV_LINK_MODE = "copy" }

Write-Host "=== ruff format check ===" -ForegroundColor Cyan
uv run --extra test ruff format --check src/ tests/
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "`n=== ruff lint ===" -ForegroundColor Cyan
uv run --extra test ruff check src/ tests/
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "`n=== web static syntax ===" -ForegroundColor Cyan
if (Get-Command node -ErrorAction SilentlyContinue) {
    node --check src/content_pipeline/web/static/app.js
    if ($LASTEXITCODE -ne 0) { $failed = $true }
    node --check src/content_pipeline/web/static/content-studio.js
    if ($LASTEXITCODE -ne 0) { $failed = $true }
} else {
    Write-Error "node is required for web static syntax checks" -ErrorAction Continue
    $failed = $true
}

Write-Host "`n=== pytest (no external, no publish) ===" -ForegroundColor Cyan
uv run --extra test pytest -m "not publish and not external" --tb=short
if ($LASTEXITCODE -ne 0) { $failed = $true }

if (-not $failed) {
    Write-Host "`n=== package build ===" -ForegroundColor Cyan
    Remove-Item -Recurse -Force dist/check -ErrorAction SilentlyContinue
    uv build --out-dir dist/check
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}

if (-not $failed) {
    Write-Host "`n=== sdist content check ===" -ForegroundColor Cyan
    $sdist = Get-ChildItem dist/check/ai_pipeline-*.tar.gz | Select-Object -First 1
    uv run python scripts/check_sdist.py $sdist.FullName
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}

if (-not $failed) {
    Write-Host "`n=== wheel content check ===" -ForegroundColor Cyan
    $wheel = Get-ChildItem dist/check/ai_pipeline-*.whl | Select-Object -First 1
    uv run python scripts/check_wheel.py $wheel.FullName
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}

if (-not $failed) {
    Write-Host "`n=== installed wheel smoke ===" -ForegroundColor Cyan
    uv pip install --reinstall --no-deps $wheel.FullName
    if ($LASTEXITCODE -ne 0) { $failed = $true }
    if (-not $failed) {
        uv pip check
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
    if (-not $failed) {
        uv run ai-pipeline capabilities | Out-Null
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
    if (-not $failed) {
        uv run ai-pipeline validate-task --task examples/tasks/dry-run/task.example.json | Out-Null
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
    if (-not $failed) {
        $tmpSmokeDir = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid().ToString()))
        Push-Location $tmpSmokeDir.FullName
        try {
            uv init --bare | Out-Null
            uv add --quiet $wheel.FullName
            if ($LASTEXITCODE -ne 0) { $failed = $true }
            if (-not $failed) {
                uv pip check
                if ($LASTEXITCODE -ne 0) { $failed = $true }
            }
            if (-not $failed) {
                uv run ai-pipeline capabilities | Out-Null
                if ($LASTEXITCODE -ne 0) { $failed = $true }
            }
            if (-not $failed) {
                uv run ai-pipeline validate-task --task (Join-Path $PSScriptRoot "../examples/tasks/dry-run/task.example.json") | Out-Null
                if ($LASTEXITCODE -ne 0) { $failed = $true }
            }
            if (-not $failed) {
                uv run python -c "from pathlib import Path; from content_pipeline.pipeline_config import load_pipeline_defaults; assert load_pipeline_defaults(Path('config/pipeline.defaults.yaml'))['enabled'] is False"
                if ($LASTEXITCODE -ne 0) { $failed = $true }
            }
        } finally {
            Pop-Location
            Remove-Item -Recurse -Force $tmpSmokeDir.FullName -ErrorAction SilentlyContinue
        }
    }
}

if ($failed) {
    Write-Host "`n[FAIL] Some checks failed. Review the output above." -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n[OK] All checks passed." -ForegroundColor Green
    exit 0
}
