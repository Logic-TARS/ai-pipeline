#!/usr/bin/env bash
# AI Popline Quality Gate (bash / Git Bash)
# Run before committing: bash scripts/check.sh

set -euo pipefail
failed=false

echo "=== ruff format check ==="
uv run ruff format --check src/ tests/ || failed=true

echo ""
echo "=== ruff lint ==="
uv run ruff check src/ tests/ || failed=true

echo ""
echo "=== pytest (no external, no publish) ==="
uv run pytest -m "not publish and not external" --tb=short || failed=true

if $failed; then
    echo ""
    echo "[FAIL] Some checks failed. Review the output above."
    exit 1
else
    echo ""
    echo "[OK] All checks passed."
    exit 0
fi
