import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from content_pipeline.errors import ExternalToolError
from content_pipeline.profiles import VideoGenProfile
from content_pipeline.settings import Settings
from content_pipeline.tools.mpt_client import _guard_generated_video, _stage_local_materials, call_mpt


def test_stage_local_materials_inside_mpt_allowlist(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    images = []
    for index in range(2):
        image = source_dir / f"source-{index}.png"
        image.write_bytes(f"image-{index}".encode())
        images.append(image)

    staged = _stage_local_materials("task-id", images, tmp_path / "mpt")

    expected_dir = (tmp_path / "mpt" / "storage" / "local_videos" / "ai-pipeline-task-id").resolve()
    assert [path.parent for path in staged] == [expected_dir, expected_dir]
    assert [path.name for path in staged] == ["01.png", "02.png"]
    assert [path.read_bytes() for path in staged] == [b"image-0", b"image-1"]


def test_call_mpt_builds_music_only_command(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "source.png"
    image.write_bytes(b"image")
    music = tmp_path / "music.mp3"
    music.write_bytes(b"music")
    mpt_dir = tmp_path / "mpt"
    mpt_dir.mkdir()
    generated = mpt_dir / "storage" / "tasks" / "ai-pipeline-job-g01" / "final-1.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"video")
    captured: list[str] = []
    captured_env: dict[str, str] = {}
    temporary_directory: Path | None = None

    def fake_run(command, **kwargs):
        nonlocal temporary_directory
        captured.extend(command)
        captured_env.update(kwargs["env"])
        temporary_directory = Path(captured_env["TEMP"])
        assert temporary_directory.is_dir()
        assert captured_env["TEMP"] == captured_env["TMP"] == captured_env["TMPDIR"]
        stdout = json.dumps({"result": {"videos": [str(generated)]}})
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("content_pipeline.tools.mpt_client.run_command", fake_run)
    settings = Settings(mpt_dir=mpt_dir, mpt_python=tmp_path / "python.exe")
    output = call_mpt(
        task_id="job-g01",
        profile=VideoGenProfile(aspect="9:16", voice_name="voice", subtitle_enabled=True),
        topic="topic",
        params={"script": "placeholder"},
        images=[image],
        output_dir=tmp_path / "output",
        settings=settings,
        custom_audio_file=music,
        video_clip_duration=5,
        video_concat_mode="sequential",
        disable_bgm=True,
        subtitle_enabled=False,
    )

    assert output.read_bytes() == b"video"
    assert temporary_directory is not None
    assert not temporary_directory.exists()
    assert captured[captured.index("--custom-audio-file") + 1] == str(music.resolve())
    assert captured[captured.index("--video-clip-duration") + 1] == "5"
    assert captured[captured.index("--video-concat-mode") + 1] == "sequential"
    assert captured[captured.index("--bgm-type") + 1] == "none"
    assert "--no-subtitle-enabled" in captured
    assert "--voice-name" not in captured
    assert "--allow-cross-post" not in captured


def test_call_mpt_cleans_temporary_directory_when_run_fails(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "source.png"
    image.write_bytes(b"image")
    mpt_dir = tmp_path / "mpt"
    mpt_dir.mkdir()
    temporary_directory: Path | None = None

    def fake_run(_command, **kwargs):
        nonlocal temporary_directory
        temporary_directory = Path(kwargs["env"]["TEMP"])
        assert temporary_directory.is_dir()
        raise RuntimeError("run failed")

    monkeypatch.setattr("content_pipeline.tools.mpt_client.run_command", fake_run)

    with pytest.raises(RuntimeError, match="run failed"):
        call_mpt(
            task_id="failed-job",
            profile=VideoGenProfile(),
            topic="topic",
            params={"script": "placeholder"},
            images=[image],
            output_dir=tmp_path / "output",
            settings=Settings(mpt_dir=mpt_dir, mpt_python=tmp_path / "python.exe"),
        )

    assert temporary_directory is not None
    assert not temporary_directory.exists()


def test_generated_video_path_must_stay_inside_mpt_dir(tmp_path: Path) -> None:
    mpt_dir = tmp_path / "mpt"
    mpt_dir.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")

    with pytest.raises(ExternalToolError, match="outside mpt_dir"):
        _guard_generated_video(outside, mpt_dir)


def test_generated_video_path_rejects_symlink(tmp_path: Path) -> None:
    mpt_dir = tmp_path / "mpt"
    mpt_dir.mkdir()
    target = mpt_dir / "target.mp4"
    target.write_bytes(b"video")
    link = mpt_dir / "link.mp4"
    link.symlink_to(target)

    with pytest.raises(ExternalToolError, match="invalid video path"):
        _guard_generated_video(link, mpt_dir)
