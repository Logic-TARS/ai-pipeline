from pathlib import Path

from PIL import Image

from content_pipeline.models import CoverParams, ErrorCode
from content_pipeline.tools.local_cover import generate_local_cover


def test_local_cover_generates_expected_dimensions_for_all_sizes(tmp_path: Path) -> None:
    expected = {
        "landscape": (1920, 1080),
        "portrait": (1080, 1440),
        "story": (1080, 1920),
    }
    for size, dimensions in expected.items():
        output = tmp_path / f"cover-{size}.png"
        result = generate_local_cover(
            params=CoverParams(title="今日 AI 行业要闻", size=size),
            output_path=output,
        )
        assert result.ok, result.message
        assert result.code == ErrorCode.OK
        assert result.tool == "LocalCover"
        with Image.open(output) as image:
            assert image.format == "PNG"
            assert (image.width, image.height) == dimensions


def test_local_cover_wraps_long_titles(tmp_path: Path) -> None:
    output = tmp_path / "cover-long.png"
    result = generate_local_cover(
        params=CoverParams(title="长" * 80, size="landscape", template="ai-poster", title_position="center"),
        output_path=output,
    )
    assert result.ok, result.message
    with Image.open(output) as image:
        assert (image.width, image.height) == (1920, 1080)


def test_local_cover_uses_background_image(tmp_path: Path) -> None:
    background = tmp_path / "background.png"
    Image.new("RGB", (2400, 1200), color="crimson").save(background)
    output = tmp_path / "cover-bg.png"
    result = generate_local_cover(
        params=CoverParams(title="带背景图的封面", background_image=background),
        output_path=output,
    )
    assert result.ok, result.message
    with Image.open(output) as image:
        assert (image.width, image.height) == (1920, 1080)


def test_local_cover_reports_missing_background(tmp_path: Path) -> None:
    result = generate_local_cover(
        params=CoverParams(title="缺失背景", background_image=tmp_path / "missing.png"),
        output_path=tmp_path / "cover.png",
    )
    assert not result.ok
    assert result.code == ErrorCode.INPUT_ERROR
    assert "does not exist" in (result.message or "")
