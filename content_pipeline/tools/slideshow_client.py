from __future__ import annotations

import hashlib
from pathlib import Path

import imageio_ffmpeg

from content_pipeline.errors import ConfigError
from content_pipeline.tools.common import run_command


SLIDESHOW_RENDER_VERSION = "static-fade-v2"


def choose_bgm(bgm_dir: Path, task_id: str, group_index: int) -> Path:
    files = sorted(path.resolve() for path in bgm_dir.glob("*.mp3") if path.is_file())
    if not files:
        raise ConfigError(f"AI art BGM directory contains no MP3 files: {bgm_dir}")
    digest = hashlib.sha256(f"{task_id}:{group_index}".encode("utf-8")).digest()
    return files[int.from_bytes(digest[:8], "big") % len(files)]


def render_slideshow(
    *,
    images: list[Path],
    bgm: Path,
    output: Path,
    seconds_per_image: float = 5.0,
    fade_seconds: float = 0.5,
    fps: int = 30,
) -> Path:
    if not images:
        raise ConfigError("cannot render an AI art slideshow without images")
    if output.is_file() and output.stat().st_size > 0:
        return output

    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for image in images:
        command.extend(
            ["-loop", "1", "-framerate", str(fps), "-t", str(seconds_per_image), "-i", str(image.resolve())]
        )
    command.extend(["-stream_loop", "-1", "-i", str(bgm.resolve())])

    filters: list[str] = []
    for index in range(len(images)):
        fade_out_start = max(0.0, seconds_per_image - fade_seconds)
        filters.append(
            f"[{index}:v]"
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1,"
            f"trim=duration={seconds_per_image},fps={fps},settb=AVTB,setpts=PTS-STARTPTS,"
            f"fade=t=in:st=0:d={fade_seconds},fade=t=out:st={fade_out_start}:d={fade_seconds}[v{index}]"
        )

    total_duration = seconds_per_image * len(images)
    if len(images) == 1:
        video_label = "v0"
    else:
        video_label = "vout"
        filters.append(
            "".join(f"[v{index}]" for index in range(len(images)))
            + f"concat=n={len(images)}:v=1:a=0[{video_label}]"
        )

    music_index = len(images)
    fade_out_start = max(0.0, total_duration - 1.0)
    filters.append(
        f"[{music_index}:a]volume=0.25,atrim=duration={total_duration},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start}:d=1[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{video_label}]",
            "-map",
            "[aout]",
            "-t",
            str(total_duration),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output.resolve()),
        ]
    )
    run_command(command, cwd=output.parent, timeout=1800, retries=0)
    return output
