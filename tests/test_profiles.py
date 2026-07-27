from pathlib import Path

import pytest

from content_pipeline.errors import ConfigError
from content_pipeline.profiles import load_profile


def test_load_profile_requires_private_visibility(tmp_path: Path) -> None:
    (tmp_path / "anime.yaml").write_text(
        """
name: anime
image_gen:
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: default
  tid: 1
  visibility: public
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_profile("anime", tmp_path)
