from __future__ import annotations

import shlex
from pathlib import Path

from content_pipeline.errors import ConfigError
from content_pipeline.profiles import ImageGenProfile
from content_pipeline.rendering import render_template
from content_pipeline.settings import Settings
from content_pipeline.tools.common import run_command
from content_pipeline.tools.gemini_mcp_client import generate_many

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def call_gemini_skill(
    *,
    profile: ImageGenProfile,
    topic: str,
    params: dict,
    output_dir: Path,
    settings: Settings,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = _ordered_images(output_dir)
    if len(existing) >= profile.count:
        return existing[: profile.count]

    if params.get("dry_run"):
        return _write_dry_run_images(output_dir, profile.count)

    prompt = render_template(profile.prompt_template, topic, {**params, "count": profile.count})
    if not settings.gemini_image_command:
        return generate_many(
            skill_dir=settings.gemini_skill_dir,
            output_dir=output_dir,
            prompt=prompt,
            count=profile.count,
            timeout=240,
            full_size=profile.full_size,
        )

    command_text = settings.gemini_image_command.format(
        prompt=prompt,
        topic=topic,
        count=profile.count,
        output_dir=str(output_dir),
    )
    run_command(shlex.split(command_text), cwd=settings.gemini_skill_dir, timeout=240, retries=2)

    images = _ordered_images(output_dir)
    if len(images) < profile.count:
        raise ConfigError(f"Gemini adapter produced {len(images)} images, expected {profile.count}: {output_dir}")
    return images[: profile.count]


def _ordered_images(output_dir: Path) -> list[Path]:
    return sorted(
        [path for path in output_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES],
        key=lambda path: path.name,
    )


def _write_dry_run_images(output_dir: Path, count: int) -> list[Path]:
    # Minimal valid JPEG bytes, enough for path/order testing without image dependencies.
    jpeg = bytes.fromhex(
        "ffd8ffe000104a46494600010101006000600000ffdb004300"
        + "08" * 64
        + "ffc00011080001000103012200021101031101ffc400140001000000000000000000000000"
        + "0000000000000000ffc4001410010000000000000000000000000000000000000000"
        + "ffda000c03010002110311003f00d2cf20ffd9"
    )
    paths: list[Path] = []
    for index in range(1, count + 1):
        path = output_dir / f"{index:02d}.jpg"
        if not path.exists():
            path.write_bytes(jpeg)
        paths.append(path)
    return paths
