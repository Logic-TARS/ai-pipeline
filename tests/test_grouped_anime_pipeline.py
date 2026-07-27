from pathlib import Path

from PIL import Image

from content_pipeline import grouped_anime_pipeline
from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput, VideoValidation
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


def _validation() -> VideoValidation:
    return VideoValidation(
        duration_seconds=10.0,
        width=1080,
        height=1920,
        aspect_ratio=0.5625,
        video_codec="h264",
        audio_codec="aac",
        decoded_video_frames=1,
        decoded_audio_frames=1,
    )


def _run_grouped_task(tmp_path: Path, monkeypatch, *, fail_second: bool = False):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("alpha1.png", "alpha2.png", "beta1.png", "beta2.png"):
        Image.new("RGB", (720, 1280), color="blue").save(source_dir / name)
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "song.mp3").write_bytes(b"music")
    calls: list[dict] = []
    music_durations: list[int] = []

    def fake_music(*, output: Path, duration_seconds: int, **_kwargs) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"trimmed music")
        music_durations.append(duration_seconds)
        return output

    def fake_mpt(*, task_id: str, images: list[Path], output_dir: Path, **kwargs) -> Path:
        calls.append({"task_id": task_id, "images": images, **kwargs})
        if fail_second and task_id.endswith("g02"):
            raise RuntimeError("second group failed")
        output_dir.mkdir(parents=True, exist_ok=True)
        video = output_dir / "final-1.mp4"
        video.write_bytes(b"video")
        return video

    monkeypatch.setattr(grouped_anime_pipeline, "prepare_music_track", fake_music)
    monkeypatch.setattr(grouped_anime_pipeline, "call_mpt", fake_mpt)
    monkeypatch.setattr(grouped_anime_pipeline, "validate_video", lambda *_args, **_kwargs: _validation())

    repo_root = Path(__file__).resolve().parents[1]
    settings = Settings(
        data_dir=tmp_path / "output",
        profiles_dir=repo_root / "profiles",
        mpt_dir=tmp_path / "mpt",
        ai_art_bgm_dir=songs,
    )
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="grouped anime test",
            content_type="grouped_anime",
            publish=False,
            params={
                "source_dir": str(source_dir),
                "archive_dir": str(tmp_path / "archive"),
                "description": "music only",
                "seconds_per_image": 5,
            },
        )
    )
    orchestrator.run(task_id)
    return orchestrator.store.get(task_id), calls, music_durations


def test_grouped_anime_calls_mpt_once_per_prefix_group(tmp_path: Path, monkeypatch) -> None:
    snapshot, calls, music_durations = _run_grouped_task(tmp_path, monkeypatch)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert len(snapshot.artifacts.groups) == 2
    assert len(calls) == 2
    assert calls[0]["task_id"].endswith("-g01")
    assert calls[1]["task_id"].endswith("-g02")
    assert [[path.name for path in call["images"]] for call in calls] == [
        ["alpha1.png", "alpha2.png"],
        ["beta1.png", "beta2.png"],
    ]
    assert music_durations == [10, 10]
    assert all(call["disable_bgm"] for call in calls)
    assert all(call["video_concat_mode"] == "sequential" for call in calls)
    assert all(call["subtitle_enabled"] is False for call in calls)
    assert all(call["allow_cross_post"] is False for call in calls)
    assert all(call["topic"] == grouped_anime_pipeline.MPT_VISUAL_ONLY_PLACEHOLDER for call in calls)
    assert all(
        call["params"]["script"] == grouped_anime_pipeline.MPT_VISUAL_ONLY_PLACEHOLDER
        for call in calls
    )
    assert snapshot.artifacts.upload_result == {"skipped": True, "reason": "publish_not_requested"}


def test_grouped_anime_keeps_successful_group_when_one_mpt_call_fails(tmp_path: Path, monkeypatch) -> None:
    snapshot, calls, _music_durations = _run_grouped_task(tmp_path, monkeypatch, fail_second=True)

    assert snapshot.status == JobStatus.PARTIAL
    assert len(calls) == 2
    assert snapshot.artifacts.groups[0].video is not None
    assert snapshot.artifacts.groups[1].video is None
    assert snapshot.artifacts.groups[1].error == "second group failed"
