from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from content_pipeline.errors import ExternalToolError, MediaValidationError
from content_pipeline.media_validation import validate_video
from content_pipeline.settings import Settings
from content_pipeline.tools.common import run_command
from content_pipeline.tools.mpt_client import _extract_video_path


@dataclass(frozen=True)
class NarratedMptResult:
    video: Path
    subtitle: Path
    task_dir: Path
    manifest: Path


ProgressCallback = Callable[[int, str, str, bool], None]


def _report_mpt_output(line: str, callback: ProgressCallback) -> None:
    """Translate known MPT log milestones into safe, conservative job progress."""
    normalized = line.lower()
    stages = (
        (("tts", "voice", "audio", "subtitle"), 30, "生成配音与字幕", "MoneyPrinterTurbo 正在生成配音或字幕"),
        (("pexels", "material", "download", "stock video"), 45, "获取视频素材", "MoneyPrinterTurbo 正在获取视频素材"),
        (("render", "compose", "combine", "final-1.mp4", "video"), 65, "渲染视频", "MoneyPrinterTurbo 正在合成视频"),
    )
    for markers, percent, phase, message in stages:
        if any(marker in normalized for marker in markers):
            callback(percent, phase, message, True)
            return


def looks_like_file_reference(value: str) -> bool:
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        return False
    return bool(
        re.fullmatch(r"(?:[A-Za-z]:)?/?.+\.(?:txt|md|json|srt)", normalized, re.IGNORECASE)
        or re.search(r"(?:MoneyPrinterTurbo/)?temp[_-]?script\w*\.(?:txt|md|json)", normalized, re.IGNORECASE)
    )


def validate_spoken_subtitle(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise MediaValidationError(f"subtitle is missing or empty: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    spoken = " ".join(
        line.strip() for line in text.splitlines() if line.strip() and "-->" not in line and not line.strip().isdigit()
    )
    if len(spoken) < 20 or looks_like_file_reference(spoken.replace(" ", "")):
        raise MediaValidationError(f"subtitle is unusable or looks like a file path: {path}")


def _has_valid_narrated_artifacts(video: Path, subtitle: Path) -> bool:
    try:
        validate_spoken_subtitle(subtitle)
        validate_video(video, expected_aspect="9:16", require_audio=True)
    except MediaValidationError:
        return False
    return True


def _briefing_voice_rate(script: str) -> float:
    """Choose a TTS rate that keeps the normal 350-500 character script near 90s."""
    # Measured on the installed zh-CN-YunxiNeural voice: 482 chars at 1.0
    # produced 74.04s. The bounded estimate keeps short and long briefings
    # close to the same target without changing the required script limits.
    estimated_seconds_at_normal = len(script) * (74.04 / 482)
    return round(max(0.55, min(1.0, estimated_seconds_at_normal / 90.0)), 2)


def _identity(title: str, script: str, input_hashes: dict[str, str] | None, voice_rate: float) -> dict[str, object]:
    return {
        "title": title,
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "input_sha256": dict(sorted((input_hashes or {}).items())),
        "voice_rate": voice_rate,
    }


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_manifest(path: Path, task_name: str, identity: dict[str, object]) -> None:
    payload = {"schema_version": "1.0", "task_id": task_name, **identity}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _archive_stale_task(task_dir: Path) -> None:
    if not task_dir.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = task_dir.with_name(f"{task_dir.name}.stale-{stamp}")
    counter = 1
    while destination.exists():
        destination = task_dir.with_name(f"{task_dir.name}.stale-{stamp}-{counter}")
        counter += 1
    shutil.move(str(task_dir), str(destination))


def call_narrated_mpt(
    *,
    task_name: str,
    title: str,
    script: str,
    output_dir: Path,
    settings: Settings,
    dry_run: bool = False,
    force_regenerate: bool = False,
    input_hashes: dict[str, str] | None = None,
    voice_rate: float | None = None,
    on_progress: ProgressCallback | None = None,
) -> NarratedMptResult:
    if looks_like_file_reference(script):
        raise MediaValidationError("narration must be spoken text, not a file path")

    output_dir.mkdir(parents=True, exist_ok=True)
    task_dir = settings.mpt_dir / "storage" / "tasks" / task_name
    target_video = output_dir / "final-1.mp4"
    target_subtitle = output_dir / "subtitle.srt"
    target_manifest = output_dir / "generation_manifest.json"
    task_manifest = task_dir / "ai-popline-manifest.json"
    resolved_voice_rate = voice_rate if voice_rate is not None else _briefing_voice_rate(script)
    identity = _identity(title, script, input_hashes, resolved_voice_rate)

    if (
        not force_regenerate
        and target_video.is_file()
        and target_subtitle.is_file()
        and _read_manifest(target_manifest) | {"schema_version": "1.0", "task_id": task_name}
        == {"schema_version": "1.0", "task_id": task_name, **identity}
        and _has_valid_narrated_artifacts(target_video, target_subtitle)
    ):
        if on_progress:
            on_progress(80, "复用既有视频", "已验证可复用的视频和字幕", False)
        return NarratedMptResult(target_video, target_subtitle, task_dir, target_manifest)

    if dry_run:
        if on_progress:
            on_progress(20, "初始化 MoneyPrinterTurbo", "正在创建干运行视频产物", False)
        target_video.write_bytes(b"DRY RUN MP4 PLACEHOLDER")
        target_subtitle.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\n" + script[:160] + "\n",
            encoding="utf-8",
        )
        _write_manifest(target_manifest, task_name, identity)
        if on_progress:
            on_progress(80, "复制视频产物", "干运行视频和字幕已写入任务目录", False)
        return NarratedMptResult(target_video, target_subtitle, task_dir, target_manifest)

    reusable_video = task_dir / "final-1.mp4"
    reusable_subtitle = task_dir / "subtitle.srt"
    reusable_script = task_dir / "script.json"
    exact_task_match = False
    if reusable_video.is_file() and reusable_subtitle.is_file() and reusable_script.is_file():
        try:
            payload = json.loads(reusable_script.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        existing_script = payload.get("script") or (payload.get("params") or {}).get("video_script")
        manifest_identity = _read_manifest(task_manifest)
        exact_task_match = existing_script == script and all(
            manifest_identity.get(key) == value for key, value in identity.items()
        )
    if not force_regenerate and exact_task_match and _has_valid_narrated_artifacts(reusable_video, reusable_subtitle):
        if on_progress:
            on_progress(80, "复用既有视频", "已验证 MoneyPrinterTurbo 的既有视频和字幕", False)
        shutil.copy2(reusable_video, target_video)
        shutil.copy2(reusable_subtitle, target_subtitle)
        _write_manifest(target_manifest, task_name, identity)
        if on_progress:
            on_progress(85, "复制视频产物", "既有视频和字幕已复制到任务目录", False)
        return NarratedMptResult(target_video, target_subtitle, task_dir, target_manifest)

    if task_dir.exists():
        _archive_stale_task(task_dir)

    command = [
        str(settings.mpt_python),
        "cli.py",
        "--video-subject",
        title,
        "--video-script",
        script,
        "--video-source",
        "pexels",
        "--video-aspect",
        "9:16",
        "--voice-name",
        "zh-CN-YunxiNeural",
        "--voice-rate",
        str(resolved_voice_rate),
        "--subtitle-enabled",
        "--task-id",
        task_name,
    ]

    stdout = ""
    timed_out = False
    if on_progress:
        on_progress(15, "初始化 MoneyPrinterTurbo", "MoneyPrinterTurbo 已启动，正在准备视频任务", False)

    def handle_output(_stream: str, line: str) -> None:
        if on_progress:
            _report_mpt_output(line, on_progress)

    try:
        result = run_command(
            command,
            cwd=settings.mpt_dir,
            timeout=3600,
            retries=2,
            env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            on_output=handle_output if on_progress else None,
        )
        stdout = result.stdout
    except subprocess.TimeoutExpired:
        timed_out = True

    source_video = task_dir / "final-1.mp4"
    if not source_video.is_file() and stdout:
        parsed = _extract_video_path(stdout, settings.mpt_dir)
        if parsed:
            source_video = parsed
            task_dir = parsed.parent
            task_manifest = task_dir / "ai-popline-manifest.json"
    source_subtitle = task_dir / "subtitle.srt"
    if not source_video.is_file():
        suffix = " after timeout" if timed_out else ""
        raise ExternalToolError(f"MPT completed{suffix} but final-1.mp4 was not found in {task_dir}")
    if not source_subtitle.is_file():
        raise ExternalToolError(f"MPT completed but subtitle.srt was not found in {task_dir}")
    if timed_out and not _has_valid_narrated_artifacts(source_video, source_subtitle):
        raise ExternalToolError(f"MPT timed out with incomplete narrated artifacts in {task_dir}")

    if on_progress:
        on_progress(80, "复制视频产物", "视频和字幕已生成，正在复制到任务目录", False)
    shutil.copy2(source_video, target_video)
    shutil.copy2(source_subtitle, target_subtitle)
    _write_manifest(task_manifest, task_name, identity)
    _write_manifest(target_manifest, task_name, identity)
    if on_progress:
        on_progress(85, "复制视频产物", "视频、字幕和生成清单已写入任务目录", False)
    return NarratedMptResult(target_video, target_subtitle, task_dir, target_manifest)
