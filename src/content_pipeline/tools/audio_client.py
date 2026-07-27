from __future__ import annotations

from pathlib import Path

import imageio_ffmpeg

from content_pipeline.errors import ConfigError
from content_pipeline.tools.common import run_command


def prepare_music_track(*, source: Path, output: Path, duration_seconds: int) -> Path:
    if duration_seconds < 1:
        raise ConfigError("music duration must be at least one second")
    if not source.is_file():
        raise ConfigError(f"music source does not exist: {source}")
    if output.is_file() and output.stat().st_size > 0:
        return output

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stream_loop",
        "-1",
        "-i",
        str(source.resolve()),
        "-t",
        str(duration_seconds),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(output.resolve()),
    ]
    run_command(command, cwd=output.parent, timeout=300, retries=0)
    if not output.is_file() or output.stat().st_size == 0:
        raise ConfigError(f"music track was not created: {output}")
    return output
