import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from content_pipeline import ai_art_pipeline
from content_pipeline.job_store import JobStore
from content_pipeline.models import AdapterResult, ErrorCode, JobStatus, TaskInput, VideoValidation
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings
from content_pipeline.tools.photo_process_client import (
    archive_source,
    call_photo_process,
    run_photo_process_adapter,
    scan_source_images,
)
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


def test_call_photo_process_forces_utf8_subprocess_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    generated = tmp_path / "生成结果.png"
    Image.new("RGB", (10, 10)).save(source)
    Image.new("RGB", (10, 10)).save(generated)
    captured: dict[str, object] = {}

    def fake_run_command(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"success": True, "image_path": str(generated)}, ensure_ascii=False) + "\n",
            stderr="",
        )

    monkeypatch.setattr("content_pipeline.tools.photo_process_client.run_command", fake_run_command)
    settings = Settings(
        photo_process_dir=tmp_path,
        photo_process_python=tmp_path / "python.exe",
    )
    settings.photo_process_python.write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    output = call_photo_process(
        source=source,
        prompt="日语风格",
        output_path=tmp_path / "out" / "0001.png",
        settings=settings,
    )

    assert captured["env"] == {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    assert "--process-name" not in captured["command"]
    assert "--preserve-source" in captured["command"]
    assert output == tmp_path / "out" / "0001.png"
    assert output.is_file()


def test_run_photo_process_adapter_returns_structured_result(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    generated = tmp_path / "generated.png"
    Image.new("RGB", (10, 12)).save(source)
    Image.new("RGB", (10, 12)).save(generated)

    def fake_run_command(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "success": True,
                    "image_path": str(generated),
                    "target_aspect_ratio": "3:4",
                },
                ensure_ascii=False,
            )
            + "\n",
            stderr="",
        )

    monkeypatch.setattr("content_pipeline.tools.photo_process_client.run_command", fake_run_command)
    settings = Settings(
        photo_process_dir=tmp_path,
        photo_process_python=tmp_path / "python.exe",
    )
    settings.photo_process_python.write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    result = run_photo_process_adapter(
        source=source,
        prompt="日语风格",
        output_path=tmp_path / "out" / "0001.png",
        settings=settings,
    )

    assert result.ok is True
    assert result.code == ErrorCode.OK
    assert result.artifacts["processed_path"] == str(tmp_path / "out" / "0001.png")
    assert result.artifacts["width"] == 10
    assert result.artifacts["height"] == 12
    assert result.artifacts["target_aspect_ratio"] == "3:4"
    assert result.evidence["validation"]["count"] == 1
    assert result.raw["photo_process_json"]["success"] is True


def test_run_photo_process_adapter_maps_failure_json_to_error_code(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (10, 10)).save(source)

    def fake_run_command(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"success": False, "error": "bad source", "error_type": "input_error"}) + "\n",
            stderr="",
        )

    monkeypatch.setattr("content_pipeline.tools.photo_process_client.run_command", fake_run_command)
    settings = Settings(photo_process_dir=tmp_path, photo_process_python=tmp_path / "python.exe")
    settings.photo_process_python.write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    result = run_photo_process_adapter(
        source=source,
        prompt="日语风格",
        output_path=tmp_path / "out" / "0001.png",
        settings=settings,
    )

    assert result.ok is False
    assert result.code == ErrorCode.INPUT_ERROR
    assert result.message == "bad source"
    assert result.raw["photo_process_json"]["error_type"] == "input_error"


def test_run_photo_process_adapter_reports_no_output_without_final_json(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (10, 10)).save(source)

    def fake_run_command(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="not json\n", stderr="")

    monkeypatch.setattr("content_pipeline.tools.photo_process_client.run_command", fake_run_command)
    settings = Settings(photo_process_dir=tmp_path, photo_process_python=tmp_path / "python.exe")
    settings.photo_process_python.write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    result = run_photo_process_adapter(
        source=source,
        prompt="日语风格",
        output_path=tmp_path / "out" / "0001.png",
        settings=settings,
    )

    assert result.ok is False
    assert result.code == ErrorCode.NO_OUTPUT
    assert result.raw["stdout_tail"] == "not json\n"


def test_run_photo_process_adapter_reports_validation_failure(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    generated = tmp_path / "generated.txt"
    Image.new("RGB", (10, 10)).save(source)
    generated.write_text("not an image", encoding="utf-8")

    def fake_run_command(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"success": True, "image_path": str(generated)}) + "\n",
            stderr="",
        )

    monkeypatch.setattr("content_pipeline.tools.photo_process_client.run_command", fake_run_command)
    settings = Settings(photo_process_dir=tmp_path, photo_process_python=tmp_path / "python.exe")
    settings.photo_process_python.write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    result = run_photo_process_adapter(
        source=source,
        prompt="日语风格",
        output_path=tmp_path / "out" / "0001.png",
        settings=settings,
    )

    assert result.ok is False
    assert result.code == ErrorCode.VALIDATION_FAILED


def test_call_photo_process_can_override_target_gem_name_and_url(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    generated = tmp_path / "generated.png"
    Image.new("RGB", (10, 10)).save(source)
    Image.new("RGB", (10, 10)).save(generated)
    captured: dict[str, object] = {}

    def fake_run_command(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"success": True, "image_path": str(generated)}, ensure_ascii=False) + "\n",
            stderr="",
        )

    monkeypatch.setattr("content_pipeline.tools.photo_process_client.run_command", fake_run_command)
    settings = Settings(
        photo_process_dir=tmp_path,
        photo_process_python=tmp_path / "python.exe",
    )
    settings.photo_process_python.write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    call_photo_process(
        source=source,
        prompt="日语风格",
        output_path=tmp_path / "out" / "0001.png",
        settings=settings,
        target_gem_name="日语视觉化",
        target_gem_url="https://gemini.google.com/gem/7aaa12067979",
    )

    command = captured["command"]
    assert command[command.index("--process-name") + 1] == "日语视觉化"
    assert "--preserve-source" in command
    assert command[command.index("--target-gem-url") + 1] == "https://gemini.google.com/gem/7aaa12067979"


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

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> AdapterResult:
        if source.name == "2.png":
            return AdapterResult(
                ok=False,
                tool="Photo-Process",
                code=ErrorCode.EXTERNAL_TOOL_FAILED,
                message="image rejected",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path)},
            evidence={"validation": {"count": 1}},
        )

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
    monkeypatch.setattr(ai_art_pipeline, "run_photo_process_adapter", fake_photo_process)
    monkeypatch.setattr(ai_art_pipeline, "render_slideshow", fake_render)
    monkeypatch.setattr(ai_art_pipeline, "validate_video", lambda *_args, **_kwargs: validation)
    monkeypatch.setattr(ai_art_pipeline, "choose_bgm", lambda *_args, **_kwargs: tmp_path / "music.mp3")

    settings = Settings(
        data_dir=tmp_path / "output",
        profiles_dir=Path("profiles"),
        pipeline_defaults_file=tmp_path / "missing-defaults.yaml",
    )
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="AI 绘画视频",
            content_type="ai_art",
            params={
                "source_dir": str(source_dir),
                "process_name": "动漫图像比例更改",
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
    assert snapshot.artifacts.source_results[0].adapter_result is not None
    assert snapshot.artifacts.source_results[0].adapter_result.code == ErrorCode.OK
    assert snapshot.artifacts.source_results[1].adapter_result is not None
    assert snapshot.artifacts.source_results[1].adapter_result.code == ErrorCode.EXTERNAL_TOOL_FAILED
    assert (source_dir / "2.png").is_file()
    assert len(list((source_dir / "已处理").glob("*.png"))) == 4
