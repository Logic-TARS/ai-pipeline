"""Test-wide isolation from the developer machine's environment.

The SAU account pre-flight (``call_sau_target`` and friends) consults the SAU
account-center bridge and local account ledger. A bridge or checkout that
happens to be available locally must not change test outcomes, so both are
isolated for every test; tests that exercise them provide explicit settings.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_live_sau_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAU_BRIDGE_URL", "")
    monkeypatch.setenv("SAU_BRIDGE_TOKEN", "")
    monkeypatch.setenv("SAU_DIR", str(tmp_path / "nonexistent-sau"))
