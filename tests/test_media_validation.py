from pathlib import Path

import av
import pytest
from PIL import Image

from content_pipeline.errors import MediaValidationError
from content_pipeline.media_validation import validate_images, validate_video


def test_validate_images_reads_real_dimensions(tmp_path: Path) -> None:
    paths = []
    for index in range(2):
        path = tmp_path / f"{index:02d}.png"
        Image.new("RGB", (90, 160), color=(index * 20, 0, 0)).save(path)
        paths.append(path)

    result = validate_images(paths, expected_count=2)

    assert result.count == 2
    assert [(item.width, item.height) for item in result.files] == [(90, 160), (90, 160)]


def test_validate_images_rejects_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "01.jpg"
    path.write_bytes(b"not an image")
    with pytest.raises(MediaValidationError, match="not decodable"):
        validate_images([path], expected_count=1)


def test_validate_video_decodes_vertical_video(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    _write_test_video(path)

    result = validate_video(path, expected_aspect="9:16", require_audio=False)

    assert result.width == 90
    assert result.height == 160
    assert result.duration_seconds > 0
    assert result.decoded_video_frames == 3


def test_validate_video_requires_audio_when_voice_is_configured(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    _write_test_video(path)
    with pytest.raises(MediaValidationError, match="audio track"):
        validate_video(path, expected_aspect="9:16", require_audio=True)


def _write_test_video(path: Path) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=3)
        stream.width = 90
        stream.height = 160
        stream.pix_fmt = "yuv420p"
        for index in range(3):
            image = Image.new("RGB", (90, 160), color=(index * 40, 20, 10))
            frame = av.VideoFrame.from_image(image)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
