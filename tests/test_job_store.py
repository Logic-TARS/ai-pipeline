from pathlib import Path

import pytest

from content_pipeline.job_store import JobDeleteConflictError, JobStore
from content_pipeline.models import (
    DeferredPublishInput,
    JobStatus,
    PipelineStep,
    PublicationAttempt,
    PublishTarget,
    TaskInput,
)


def test_progress_is_persisted_as_an_event_without_local_paths(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "output")
    task_id = store.create(TaskInput(description="进度测试")).task_id

    snapshot = store.set_progress(
        task_id,
        percent=45,
        phase="获取 G:\\private\\source",
        message="正在读取 G:\\private\\source\\clip.mp4",
        is_estimate=True,
    )

    assert snapshot.progress is not None
    assert snapshot.progress.percent == 45
    assert snapshot.progress.is_estimate is True
    assert "G:" not in snapshot.progress.phase
    assert "G:" not in snapshot.progress.message
    events = store.events_path(task_id).read_text(encoding="utf-8")
    assert '"event": "progress_updated"' in events
    assert "G:" not in events



def test_delete_job_removes_terminal_job_and_blocks_running_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "output")
    terminal = store.create(TaskInput(description="可删除任务")).task_id
    running = store.create(TaskInput(description="运行中任务")).task_id
    store.finish(terminal, JobStatus.SUCCEEDED)
    store.mark_running(running, PipelineStep.ROUTE)

    store.delete_job(terminal)

    assert not store.job_dir(terminal).exists()
    with pytest.raises(FileNotFoundError):
        store.get(terminal)
    with pytest.raises(JobDeleteConflictError):
        store.delete_job(running)
    assert store.job_dir(running).exists()


def test_delete_jobs_reports_partial_results(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "output")
    first = store.create(TaskInput(description="第一项")).task_id
    blocked = store.create(TaskInput(description="运行中")).task_id
    store.finish(first, JobStatus.FAILED, "failed for test")
    store.mark_running(blocked, PipelineStep.ROUTE)
    missing = "0" * 32

    result = store.delete_jobs([first, blocked, missing])

    assert result["deleted"] == [first]
    assert result["blocked"] == [blocked]
    assert result["not_found"] == [missing]
    assert result["failed"] == []



def test_rename_job_preserves_original_task_and_records_event(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "output")
    task_id = store.create(TaskInput(description="原始任务名称")).task_id

    renamed = store.rename_job(task_id, "  新显示名称  ")

    assert renamed.display_name == "新显示名称"
    assert renamed.task.description == "原始任务名称"
    persisted = store.get(task_id)
    assert persisted.display_name == "新显示名称"
    assert persisted.task.description == "原始任务名称"
    events = store.events_path(task_id).read_text(encoding="utf-8")
    assert '"event": "job_metadata_updated"' in events
    assert "新显示名称" in events


def test_delete_job_blocks_active_publication(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "output")
    task_id = store.create(TaskInput(description="正在发布")).task_id
    store.finish(task_id, JobStatus.SUCCEEDED)
    snapshot = store.get(task_id)
    snapshot.publication_attempts.append(
        PublicationAttempt(
            attempt_id="a" * 32,
            request=DeferredPublishInput(
                publish_targets=[PublishTarget(platform="douyin", account="test")],
                title="测试标题",
            ),
            video_sha256="b" * 64,
            requested_at="2026-08-11T00:00:00+00:00",
        )
    )
    store.save(snapshot)

    with pytest.raises(JobDeleteConflictError, match="active publication"):
        store.delete_job(task_id)

    assert store.job_dir(task_id).exists()
