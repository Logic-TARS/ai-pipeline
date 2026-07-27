import shutil
from pathlib import Path

from PIL import Image

from content_pipeline import ai_art_pipeline
from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput, VideoValidation
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings
from content_pipeline.tools.photo_process_client import archive_source, scan_source_images
from content_pipeline.tools.slideshow_client import choose_bgm, render_slideshow


def test_scan_source_images_uses_natural_order_and_archive_is_collision_safe(tmp_path: Path) -> None:
    for name in ("10.png", "2.png", "1.png"):
        Image.new("RGB", (10, 10)).save(tmp_path / name)
    (tmp_path / "ignore.txt").write_text("x")

    assert [path.name for path in scan_source_images(tmp_path)] == ["1.png", "2.png", "10.png"]

    archive_dir = tmp_path / "已处理"
    first = archive_source(tmp_path / "1.png", archive_dir)
    Image.new("RGB", (10, 10)).save(tmp_path / "1.png")
    second = archive_source(tmp_path / "1.png", archive_dir)
    assert first.name == "1.png"
    assert second.name == "1_1.png"


def test_choose_bgm_is_stable(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"song-{index}.mp3").write_bytes(b"music")
    assert choose_bgm(tmp_path, "task", 1) == choose_bgm(tmp_path, "task", 1)


def test_render_slideshow_builds_static_fade_vertical_command(tmp_path: Path, monkeypatch) -> None:
    images = []
    for index in range(2):
        path = tmp_path / f"{index}.png"
        path.write_bytes(b"image")
        images.append(path)
    bgm = tmp_path / "music.mp3"
    bgm.write_bytes(b"music")
    captured: list[str] = []

    def fake_run(command, **_kwargs):
        captured.extend(command)

    monkeypatch.setattr("content_pipeline.tools.slideshow_client.run_command", fake_run)
    monkeypatch.setattr("content_pipeline.tools.slideshow_client.imageio_ffmpeg.get_ffmpeg_exe", lambda: "ffmpeg")
    output = render_slideshow(images=images, bgm=bgm, output=tmp_path / "out.mp4")

    filters = captured[captured.index("-filter_complex") + 1]
    assert "zoompan" not in filters
    assert "scale=1080:1920" in filters
    assert "crop=1080:1920" in filters
    assert "fade=t=in" in filters
    assert "concat=n=2" in filters
    assert output.name == "out.mp4"


def test_ai_art_skips_failed_image_regroups_and_archives_successes(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("1.png", "2.png", "3.png", "4.png", "5.png"):
        Image.new("RGB", (90, 160), color="blue").save(source_dir / name)

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> Path:
        if source.name == "2.png":
            raise RuntimeError("image rejected")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return output_path

    def fake_render(*, output: Path, **_kwargs) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return output

    validation = VideoValidation(
        duration_seconds=18.5,
        width=1080,
        height=1920,
        aspect_ratio=0.5625,
        video_codec="h264",
        audio_codec="aac",
        decoded_video_frames=1,
        decoded_audio_frames=1,
    )
    monkeypatch.setattr(ai_art_pipeline, "call_photo_process", fake_photo_process)
    monkeypatch.setattr(ai_art_pipeline, "render_slideshow", fake_render)
    monkeypatch.setattr(ai_art_pipeline, "validate_video", lambda *_args, **_kwargs: validation)
    monkeypatch.setattr(ai_art_pipeline, "choose_bgm", lambda *_args, **_kwargs: tmp_path / "music.mp3")

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="AI 绘画视频",
            content_type="ai_art",
            params={
                "source_dir": str(source_dir),
                "image_prompt": "改成水彩画",
                "title": "水彩作品",
                "group_size": 4,
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.PARTIAL
    assert len(snapshot.artifacts.images) == 4
    assert len(snapshot.artifacts.groups) == 1
    assert len(snapshot.artifacts.groups[0].processed_images) == 4
    assert (source_dir / "2.png").is_file()
    assert len(list((source_dir / "已处理").glob("*.png"))) == 4
