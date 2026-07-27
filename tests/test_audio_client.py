from pathlib import Path

from content_pipeline.tools.audio_client import prepare_music_track


def test_prepare_music_track_loops_and_trims_to_requested_duration(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"music")
    output = tmp_path / "out" / "music.mp3"
    captured: list[str] = []

    def fake_run(command, **_kwargs):
        captured.extend(command)
        Path(command[-1]).write_bytes(b"trimmed")

    monkeypatch.setattr("content_pipeline.tools.audio_client.run_command", fake_run)
    monkeypatch.setattr("content_pipeline.tools.audio_client.imageio_ffmpeg.get_ffmpeg_exe", lambda: "ffmpeg")

    result = prepare_music_track(source=source, output=output, duration_seconds=20)

    assert result == output
    assert captured[captured.index("-stream_loop") + 1] == "-1"
    assert captured[captured.index("-t") + 1] == "20"
    assert result.read_bytes() == b"trimmed"
