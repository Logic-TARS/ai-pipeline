from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, PipelineStep
from content_pipeline.settings import Settings

runner = importlib.import_module("content_pipeline.ai_briefing_runner")


def test_ai_briefing_runner_rejects_invalid_handoff_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["ai-briefing", "--handoff-wait-seconds", "3601"])

    with pytest.raises(SystemExit):
        runner.main()


def test_ai_briefing_runner_submits_validated_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "output", ai_briefing_dir=tmp_path / "briefings")
    captured = {}

    class FakeOrchestrator:
        def __init__(self, settings: Settings, store: JobStore) -> None:
            self.settings = settings
            self.store = store

        def submit(self, task):  # noqa: ANN001
            captured["task"] = task
            return self.store.create(task).task_id

        def run(self, task_id: str) -> None:
            snapshot = self.store.mark_running(task_id, PipelineStep.ROUTE)
            self.store.finish(snapshot.task_id, JobStatus.SUCCEEDED)

    monkeypatch.setattr(sys, "argv", ["ai-briefing", "--date", "20260720", "--dry-run", "--handoff-wait-seconds", "0"])
    monkeypatch.setattr(runner, "load_settings", lambda: settings)
    monkeypatch.setattr(runner, "Orchestrator", FakeOrchestrator)

    assert runner.main() == 0
    assert captured["task"].content_type == "ai_briefing"
    assert captured["task"].params["handoff_wait_seconds"] == 0
    assert captured["task"].params["script_writer"] == "rule"
    assert captured["task"].params["dry_run"] is True
