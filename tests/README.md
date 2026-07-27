# Test layout

Current tests remain at the repository test root for compatibility. New tests should use:

- `tests/unit/` for pure Python tests with no subprocess/browser/tool calls.
- `tests/integration/` for adapter tests using mocked local tools or small generated fixtures.
- `tests/e2e/` for full environment smoke tests.
- `tests/fixtures/` for reusable static inputs.

Markers:

- `external`: calls real Gemini, Photo-Process, MPT, SAU, browser, or ffmpeg installations.
- `smoke`: end-to-end smoke test requiring a configured workstation.
- `publish`: can publish or draft to social platforms; excluded by default.
