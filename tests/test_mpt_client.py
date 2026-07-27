import json
from pathlib import Path
from subprocess import CompletedProcess

from content_pipeline.profiles import VideoGenProfile
from content_pipeline.settings import Settings
from content_pipeline.tools.mpt_client import _stage_local_materials, call_mpt


def test_stage_local_materials_inside_mpt_allowlist(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    images = []
    for index in range(2):
        image = source_dir / f"source-{index}.png"
        image.write_bytes(f"image-{index}".encode())
        images.append(image)

    staged = _stage_local_materials("task-id", images, tmp_path / "mpt")

    expected_dir = (tmp_path / "mpt" / "storage" / "local_videos" / "ai-popline-task-id").resolve()
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
    generated = mpt_dir / "storage" / "tasks" / "ai-popline-job-g01" / "final-1.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"video")
    captured: list[str] = []

    def fake_run(command, **_kwargs):
        captured.extend(command)
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
    assert captured[captured.index("--custom-audio-file") + 1] == str(music.resolve())
    assert captured[captured.index("--video-clip-duration") + 1] == "5"
    assert captured[captured.index("--video-concat-mode") + 1] == "sequential"
    assert captured[captured.index("--bgm-type") + 1] == "none"
    assert "--no-subtitle-enabled" in captured
    assert "--voice-name" not in captured
    assert "--allow-cross-post" not in captured
