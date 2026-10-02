import json
from pathlib import Path

import pytest

from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator, run_task_file
from content_pipeline.settings import Settings


def test_dry_run_pipeline_succeeds(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="动漫短片",
            content_type="anime",
            topic="周五下班",
            params={"script": "四格故事", "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.SUCCEEDED
    assert len(snapshot.artifacts.images) == 4
    assert snapshot.artifacts.video is not None
    assert snapshot.artifacts.upload_result == {
        "skipped": True,
        "reason": "publish_not_requested",
    }


def test_dry_run_only_previews_upload_when_publish_is_explicit(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="动漫短片",
            content_type="anime",
            topic="周五下班",
            publish=True,
            params={"script": "四格故事", "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.SUCCEEDED
    assert snapshot.artifacts.upload_result is not None
    assert snapshot.artifacts.upload_result["dry_run"] is True
    assert snapshot.artifacts.upload_result["visibility"] == "private"


def test_run_task_file_rejects_unknown_known_pipeline_params(tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "description": "动漫短片",
                "content_type": "anime",
                "topic": "周五下班",
                "params": {"script": "四格故事", "dry_run": True, "unexpected": "value"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        run_task_file(task_file)
