# AI Popline Quality Gate (PowerShell)
# Run before committing: .\scripts\check.ps1

$ErrorActionPreference = "Stop"
$failed = $false

Write-Host "=== ruff format check ===" -ForegroundColor Cyan
uv run ruff format --check src/ tests/
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "`n=== ruff lint ===" -ForegroundColor Cyan
uv run ruff check src/ tests/
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "`n=== pytest (no external, no publish) ===" -ForegroundColor Cyan
uv run pytest -m "not publish and not external" --tb=short
if ($LASTEXITCODE -ne 0) { $failed = $true }

if ($failed) {
    Write-Host "`n[FAIL] Some checks failed. Review the output above." -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n[OK] All checks passed." -ForegroundColor Green
    exit 0
}
