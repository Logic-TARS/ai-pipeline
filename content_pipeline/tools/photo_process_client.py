from __future__ import annotations

import json
import shutil
from pathlib import Path

from content_pipeline.errors import ConfigError, ExternalToolError
from content_pipeline.media_validation import validate_images
from content_pipeline.settings import Settings
from content_pipeline.tools.common import run_command


SOURCE_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def scan_source_images(source_dir: Path, source_files: list[str] | None = None) -> list[Path]:
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ConfigError(f"AI art source directory does not exist: {source_dir}")
    if source_files:
        selected: list[Path] = []
        for filename in source_files:
            if Path(filename).name != filename:
                raise ConfigError(f"source_files entries must be plain filenames: {filename}")
            path = (source_dir / filename).resolve()
            if path.parent != source_dir or not path.is_file() or path.suffix.lower() not in SOURCE_IMAGE_SUFFIXES:
                raise ConfigError(f"selected source image is invalid or missing: {path}")
            selected.append(path)
        if len(set(selected)) != len(selected):
            raise ConfigError("source_files must not contain duplicates")
        return selected
    return sorted(
        (path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in SOURCE_IMAGE_SUFFIXES),
        key=_natural_key,
    )


def call_photo_process(
    *,
    source: Path,
    prompt: str,
    output_path: Path,
    settings: Settings,
) -> Path:
    for existing in sorted(output_path.parent.glob(f"{output_path.stem}.*")) if output_path.parent.exists() else []:
        if existing.suffix.lower() in SOURCE_IMAGE_SUFFIXES and existing.is_file():
            validate_images([existing], 1)
            return existing
    if not settings.photo_process_python.is_file():
        raise ConfigError(f"Photo-Process Python not found: {settings.photo_process_python}")
    main_py = settings.photo_process_dir / "main.py"
    if not main_py.is_file():
        raise ConfigError(f"Photo-Process entrypoint not found: {main_py}")

    result = run_command(
        [
            str(settings.photo_process_python),
            str(main_py),
            "comic",
            "--image",
            str(source.resolve()),
            "--prompt",
            prompt,
            "--json",
        ],
        cwd=settings.photo_process_dir,
        timeout=900,
        retries=0,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    payload = _parse_json_result(result.stdout)
    if not payload.get("success"):
        raise ExternalToolError(
            f"Photo-Process failed [{payload.get('error_type', 'unknown')}]: {payload.get('error', 'unknown error')}"
        )
    generated = Path(str(payload.get("image_path", ""))).expanduser()
    if not generated.is_absolute():
        generated = settings.photo_process_dir / generated
    validate_images([generated], 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target = output_path.with_suffix(generated.suffix.lower())
    shutil.copy2(generated, target)
    validate_images([target], 1)
    return target


def archive_source(source: Path, archive_dir: Path) -> Path:
    if not source.exists():
        raise ConfigError(f"source image is no longer available for archiving: {source}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / source.name
    counter = 1
    while target.exists():
        target = archive_dir / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    return Path(shutil.move(str(source), str(target)))


def _parse_json_result(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ExternalToolError(f"Photo-Process did not return a JSON result: {stdout[-1000:]}")


def _natural_key(path: Path) -> list[object]:
    import re

    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]
