#!/usr/bin/env bash
# AI Pipeline Quality Gate (bash / Git Bash)
# Run before committing: bash scripts/check.sh

set -euo pipefail
failed=false
tmp_smoke_dir=""
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

cleanup() {
    if [[ -n "${tmp_smoke_dir:-}" && -d "$tmp_smoke_dir" ]]; then
        rm -rf "$tmp_smoke_dir"
    fi
}
trap cleanup EXIT

echo "=== ruff format check ==="
uv run --extra test ruff format --check src/ tests/ || failed=true

echo ""
echo "=== ruff lint ==="
uv run --extra test ruff check src/ tests/ || failed=true

echo ""
echo "=== web static syntax ==="
if command -v node >/dev/null 2>&1; then
    node --check src/content_pipeline/web/static/app.js || failed=true
    node --check src/content_pipeline/web/static/content-studio.js || failed=true
else
    echo "node is required for web static syntax checks" >&2
    failed=true
fi

echo ""
echo "=== pytest (no external, no publish) ==="
uv run --extra test pytest -m "not publish and not external" --tb=short || failed=true

if ! $failed; then
    echo ""
    echo "=== package build ==="
    rm -rf dist/check
    uv build --out-dir dist/check || failed=true
fi

if ! $failed; then
    echo ""
    echo "=== sdist content check ==="
    sdist_path=$(ls dist/check/ai_pipeline-*.tar.gz | head -n 1)
    uv run python scripts/check_sdist.py "$sdist_path" || failed=true
fi

if ! $failed; then
    echo ""
    echo "=== wheel content check ==="
    wheel_path=$(ls dist/check/ai_pipeline-*.whl | head -n 1)
    uv run python scripts/check_wheel.py "$wheel_path" || failed=true
fi

if ! $failed; then
    echo ""
    echo "=== installed wheel smoke ==="
    uv pip install --reinstall --no-deps "$wheel_path" || failed=true
    if ! $failed; then
        uv pip check || failed=true
    fi
    if ! $failed; then
        uv run ai-pipeline capabilities >/dev/null || failed=true
    fi
    if ! $failed; then
        uv run ai-pipeline validate-task --task examples/tasks/dry-run/task.example.json >/dev/null || failed=true
    fi
    if ! $failed; then
        tmp_smoke_dir=$(mktemp -d)
        wheel_abs=$(realpath "$wheel_path")
        (cd "$tmp_smoke_dir" && uv init --bare >/dev/null && uv add --quiet "$wheel_abs" && uv pip check && uv run ai-pipeline capabilities >/dev/null && uv run ai-pipeline validate-task --task "$OLDPWD/examples/tasks/dry-run/task.example.json" >/dev/null && uv run python -c "from pathlib import Path; from content_pipeline.pipeline_config import load_pipeline_defaults; assert load_pipeline_defaults(Path('config/pipeline.defaults.yaml'))['enabled'] is False") || failed=true
    fi
fi

if $failed; then
    echo ""
    echo "[FAIL] Some checks failed. Review the output above."
    exit 1
else
    echo ""
    echo "[OK] All checks passed."
    exit 0
fi
