# Smoke Testing

## Quick Reference

```bash
# Default: skip external and publish tests
pytest

# Run external tool tests (requires configured tools)
RUN_EXTERNAL_TESTS=1 pytest -m external

# DANGER: actually publishes to social platforms
RUN_PUBLISH_TESTS=1 pytest -m publish

# Run everything except publish
pytest -m "not publish"

# Run a specific smoke test
RUN_EXTERNAL_TESTS=1 pytest tests/test_japanese_pipeline.py -m external -v
```

## Test Markers

| Marker | Purpose | Default | Env Var Required |
|---|---|---|---|
| `external` | Tests calling real external tools (Gemini, Photo-Process, MPT, SAU) | Skipped | `RUN_EXTERNAL_TESTS=1` |
| `smoke` | End-to-end smoke tests requiring full environment | Skipped | `RUN_EXTERNAL_TESTS=1` |
| `publish` | Tests that actually publish to social platforms | **Always skipped** | `RUN_PUBLISH_TESTS=1` |

## Pre-flight Checklist

Before running external tests:

1. Run `ai-popline doctor` — verify all tool paths and executables
2. Confirm `.env` is configured with valid paths
3. Ensure no conflicting browser processes (production profile must be free)
4. Verify external tools are installed and working independently
5. For publish tests: log into target platform accounts first

## Writing Smoke Tests

```python
import os
import pytest

@pytest.mark.external
def test_real_photo_process():
    if not os.getenv("RUN_EXTERNAL_TESTS"):
        pytest.skip("RUN_EXTERNAL_TESTS not set")
    # ... real external tool call

@pytest.mark.publish
def test_real_upload():
    if not os.getenv("RUN_PUBLISH_TESTS"):
        pytest.skip("RUN_PUBLISH_TESTS not set")
    # ... real publish call
```
