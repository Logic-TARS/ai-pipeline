from __future__ import annotations

from pathlib import Path


def test_bash_quality_gate_includes_distribution_build() -> None:
    script = Path("scripts/check.sh").read_text(encoding="utf-8")

    assert 'export UV_LINK_MODE="${UV_LINK_MODE:-copy}"' in script
    assert 'tmp_smoke_dir=""' in script
    assert "cleanup()" in script
    assert '[[ -n "${tmp_smoke_dir:-}" && -d "$tmp_smoke_dir" ]]' in script
    assert "trap cleanup EXIT" in script
    assert "uv run --extra test ruff format --check src/ tests/" in script
    assert "uv run --extra test ruff check src/ tests/" in script
    assert "command -v node" in script
    assert "node --check src/content_pipeline/web/static/app.js" in script
    assert "node --check src/content_pipeline/web/static/content-studio.js" in script
    assert 'uv run --extra test pytest -m "not publish and not external" --tb=short' in script
    assert "uv build --out-dir dist/check" in script
    assert "uv run python scripts/check_sdist.py" in script
    assert "uv run python scripts/check_wheel.py" in script
    assert "uv pip install --reinstall --no-deps" in script
    assert script.count("uv pip check") == 2
    assert "uv run ai-pipeline capabilities >/dev/null" in script
    assert "uv run ai-pipeline validate-task --task examples/tasks/dry-run/task.example.json >/dev/null" in script
    assert "tmp_smoke_dir=$(mktemp -d)" in script
    assert 'wheel_abs=$(realpath "$wheel_path")' in script
    assert "uv init --bare >/dev/null" in script
    assert 'uv add --quiet "$wheel_abs"' in script
    assert "uv run ai-pipeline capabilities >/dev/null" in script
    assert (
        'uv run ai-pipeline validate-task --task "$OLDPWD/examples/tasks/dry-run/task.example.json" >/dev/null'
        in script
    )
    assert "load_pipeline_defaults(Path('config/pipeline.defaults.yaml'))['enabled'] is False" in script
    assert script.index("node --check src/content_pipeline/web/static/app.js") < script.index(
        "uv run --extra test pytest"
    )
    assert script.index("uv run --extra test pytest") < script.index("uv build --out-dir dist/check")
    assert script.index("uv build --out-dir dist/check") < script.index("sdist content check")
    assert script.index("sdist content check") < script.index("wheel content check")
    assert script.index("wheel content check") < script.index("installed wheel smoke")
    assert "if ! $failed; then" in script


def test_powershell_quality_gate_includes_distribution_build() -> None:
    script = Path("scripts/check.ps1").read_text(encoding="utf-8")

    assert 'if (-not $env:UV_LINK_MODE) { $env:UV_LINK_MODE = "copy" }' in script
    assert "uv run --extra test ruff format --check src/ tests/" in script
    assert "uv run --extra test ruff check src/ tests/" in script
    assert "Get-Command node" in script
    assert "node --check src/content_pipeline/web/static/app.js" in script
    assert "node --check src/content_pipeline/web/static/content-studio.js" in script
    assert 'uv run --extra test pytest -m "not publish and not external" --tb=short' in script
    assert "uv build --out-dir dist/check" in script
    assert "uv run python scripts/check_sdist.py" in script
    assert "uv run python scripts/check_wheel.py" in script
    assert "uv pip install --reinstall --no-deps" in script
    assert script.count("uv pip check") == 2
    assert "uv run ai-pipeline capabilities | Out-Null" in script
    assert "uv run ai-pipeline validate-task --task examples/tasks/dry-run/task.example.json | Out-Null" in script
    assert "$tmpSmokeDir = New-Item -ItemType Directory" in script
    assert "} finally {" in script
    assert "Remove-Item -Recurse -Force $tmpSmokeDir.FullName -ErrorAction SilentlyContinue" in script
    assert "uv init --bare | Out-Null" in script
    assert "uv add --quiet $wheel.FullName" in script
    assert "uv run ai-pipeline capabilities | Out-Null" in script
    assert (
        "uv run ai-pipeline validate-task --task "
        '(Join-Path $PSScriptRoot "../examples/tasks/dry-run/task.example.json") | Out-Null' in script
    )
    assert "load_pipeline_defaults(Path('config/pipeline.defaults.yaml'))['enabled'] is False" in script
    assert script.index("node --check src/content_pipeline/web/static/app.js") < script.index(
        "uv run --extra test pytest"
    )
    assert script.index("uv run --extra test pytest") < script.index("uv build --out-dir dist/check")
    assert script.index("uv build --out-dir dist/check") < script.index("sdist content check")
    assert script.index("sdist content check") < script.index("wheel content check")
    assert script.index("wheel content check") < script.index("installed wheel smoke")
    assert "if (-not $failed)" in script
