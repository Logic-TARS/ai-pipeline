from pathlib import Path

from content_pipeline.profiles import ImageGenProfile
from content_pipeline.settings import Settings
from content_pipeline.tools.gemini_client import _ordered_images, call_gemini_skill


def test_ordered_images_ignores_symlinked_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    target = tmp_path / "outside.png"
    target.write_bytes(b"image")
    link = output_dir / "01.png"
    link.symlink_to(target)
    real = output_dir / "02.png"
    real.write_bytes(b"image")

    assert _ordered_images(output_dir) == [real]


def test_command_mode_rejects_only_symlinked_outputs(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "output"
    target = tmp_path / "outside.png"
    target.write_bytes(b"image")

    def fake_run(_command, **_kwargs):
        link = output_dir / "01.png"
        link.symlink_to(target)

    monkeypatch.setattr("content_pipeline.tools.gemini_client.run_command", fake_run)

    profile = ImageGenProfile(prompt_template="{topic}", count=1)
    settings = Settings(
        gemini_image_command='python -c "pass"',
        gemini_skill_dir=tmp_path,
    )

    try:
        call_gemini_skill(profile=profile, topic="topic", params={}, output_dir=output_dir, settings=settings)
    except Exception as exc:
        assert "produced 0 images" in str(exc)
    else:
        raise AssertionError("symlinked Gemini output was accepted")
