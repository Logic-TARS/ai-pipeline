from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_pipeline.models import AdapterResult, CoverParams, ErrorCode

__all__ = ["generate_local_cover"]

_TOOL_NAME = "LocalCover"
_SIZES = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1440),
    "story": (1080, 1920),
}
_GRADIENTS = {
    "default": ((16, 32, 62), (58, 96, 168)),
    "ai-poster": ((24, 18, 48), (96, 60, 168)),
}
_ACCENT = (96, 165, 250)
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)
_MAX_TITLE_LINES = 4


def generate_local_cover(*, params: CoverParams, output_path: Path) -> AdapterResult:
    """Render a cover image locally with Pillow, no external service required."""
    width, height = _SIZES[params.size]
    try:
        image = _background_image(params, width, height)
        draw = ImageDraw.Draw(image)
        _draw_title(draw, params, width, height)
        _atomic_save(image, output_path)
    except (OSError, ValueError) as exc:
        return AdapterResult(
            ok=False,
            tool=_TOOL_NAME,
            code=ErrorCode.INPUT_ERROR,
            message=f"local cover generation failed: {exc}"[:2000],
        )
    return AdapterResult(
        ok=True,
        tool=_TOOL_NAME,
        code=ErrorCode.OK,
        artifacts={"cover_path": str(output_path)},
        evidence={"generator": "local_pillow", "size": params.size, "template": params.template},
    )


def _background_image(params: CoverParams, width: int, height: int):
    if params.background_image is not None:
        source = params.background_image.expanduser()
        if not source.is_file():
            raise ValueError(f"background image does not exist: {source}")
        base = Image.open(source).convert("RGB")
        scale = max(width / base.width, height / base.height) * params.background_scale
        resized = base.resize((max(1, round(base.width * scale)), max(1, round(base.height * scale))), Image.LANCZOS)
        left = round((resized.width - width) * params.background_position_x / 100)
        top = round((resized.height - height) * params.background_position_y / 100)
        image = resized.crop((left, top, left + width, top + height))
        # Darken the photo so the title stays readable.
        overlay = Image.new("RGB", (width, height), (0, 0, 0))
        return Image.blend(image, overlay, 0.42)

    top_color, bottom_color = _GRADIENTS.get(params.template, _GRADIENTS["default"])
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top_color, bottom_color, strict=True))
        draw.line([(0, y), (width, y)], fill=color)
    return image


def _load_font(size: int):
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_title(draw, font, title: str, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in title:
        trial = current + character
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(current)
            current = character
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_title(draw, params: CoverParams, width: int, height: int) -> None:
    margin_x = round(width * 0.08)
    max_text_width = width - margin_x * 2
    font_size = round(width * 0.075)
    min_size = round(width * 0.035)
    while True:
        font = _load_font(font_size)
        lines = _wrap_title(draw, font, params.title, max_text_width)
        if len(lines) <= _MAX_TITLE_LINES or font_size <= min_size:
            break
        font_size -= 4
    lines = lines[:_MAX_TITLE_LINES]
    line_height = round(font_size * 1.35)
    block_height = line_height * len(lines)
    top = round((height - block_height) / 2)

    # Accent bar above the title block.
    bar_width = round(width * 0.09)
    bar_height = max(6, round(height * 0.008))
    bar_x = margin_x if params.title_position == "left" else round((width - bar_width) / 2)
    bar_y = top - round(height * 0.045)
    draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], fill=_ACCENT)

    for index, line in enumerate(lines):
        if params.title_position == "center":
            text_width = draw.textlength(line, font=font)
            x = (width - text_width) / 2
        else:
            x = margin_x
        y = top + index * line_height
        shadow = max(2, round(font_size * 0.04))
        draw.text((x + shadow, y + shadow), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))


def _atomic_save(image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            image.save(handle, format="PNG")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
