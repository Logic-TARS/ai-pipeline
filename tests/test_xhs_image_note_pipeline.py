import shutil
from pathlib import Path

from PIL import Image

from content_pipeline import xhs_image_note_pipeline
from content_pipeline.job_store import JobStore
from content_pipeline.models import AdapterResult, ErrorCode, JobStatus, PublishTarget, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


def test_xhs_image_note_processes_images_without_rendering_video(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("1.png", "2.png"):
        Image.new("RGB", (900, 1200), color="red").save(source_dir / name)
    render_called = False

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> AdapterResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path), "width": 900, "height": 1200, "target_aspect_ratio": "3:4"},
            evidence={"validation": {"count": 1}},
        )

    def fake_render(*_args, **_kwargs):
        nonlocal render_called
        render_called = True

    monkeypatch.setattr(xhs_image_note_pipeline, "run_photo_process_adapter", fake_photo_process)
    monkeypatch.setattr("content_pipeline.tools.slideshow_client.render_slideshow", fake_render)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="小红书图文",
            content_type="xhs_image_note",
            params={
                "source_dir": str(source_dir),
                "image_prompt": "改成 3:4 小红书竖图",
                "title": "图文标题",
            },
        )
    )

    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert len(snapshot.artifacts.images) == 2
    assert snapshot.artifacts.video is None
    assert snapshot.artifacts.groups == []
    assert snapshot.artifacts.validation.images is not None
    assert snapshot.artifacts.validation.images.count == 2
    assert snapshot.artifacts.upload_result == {"skipped": True, "reason": "publish_not_requested"}
    assert render_called is False


def test_xhs_image_note_rejects_non_3_4_processed_image(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    Image.new("RGB", (1000, 1000), color="blue").save(source_dir / "1.png")

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> AdapterResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path), "width": 1000, "height": 1000},
            evidence={"validation": {"count": 1}},
        )

    monkeypatch.setattr(xhs_image_note_pipeline, "run_photo_process_adapter", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="小红书图文",
            content_type="xhs_image_note",
            params={
                "source_dir": str(source_dir),
                "image_prompt": "改成 3:4 小红书竖图",
                "title": "图文标题",
            },
        )
    )

    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.FAILED
    assert "usable 3:4" in (snapshot.error or "")
    assert snapshot.artifacts.images == []


def test_xhs_image_note_dry_run_uploads_all_images_as_one_note(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("1.png", "2.png"):
        Image.new("RGB", (900, 1200), color="green").save(source_dir / name)
    captured: dict[str, object] = {}

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> AdapterResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path), "width": 900, "height": 1200, "target_aspect_ratio": "3:4"},
            evidence={"validation": {"count": 1}},
        )

    def fake_upload(**kwargs):
        captured.update(kwargs)
        return {"success": True, "dry_run": True, "command": ["sau", "xiaohongshu", "upload-note"]}

    monkeypatch.setattr(xhs_image_note_pipeline, "run_photo_process_adapter", fake_photo_process)
    monkeypatch.setattr(xhs_image_note_pipeline, "call_sau_xiaohongshu_note", fake_upload)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="任务描述正文",
            content_type="xhs_image_note",
            publish=True,
            publish_targets=[PublishTarget(platform="xiaohongshu", account="小红书账号")],
            params={
                "source_dir": str(source_dir),
                "image_prompt": "改成 3:4 小红书竖图",
                "title": "图文标题",
                "note": "任务描述正文",
                "tags": ["AI绘画", "小红书图文"],
                "dry_run": True,
            },
        )
    )

    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert captured["account"] == "小红书账号"
    assert captured["title"] == "图文标题"
    assert captured["note"] == "任务描述正文"
    assert captured["tags"] == ["AI绘画", "小红书图文"]
    assert captured["dry_run"] is True
    assert len(captured["images"]) == 2
    assert set(snapshot.artifacts.publish_results) == {"xiaohongshu:小红书账号"}
    assert snapshot.artifacts.upload_result == {"publish_results": snapshot.artifacts.publish_results}
