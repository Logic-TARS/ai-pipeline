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


def test_load_profile_wraps_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "anime.yaml").write_text("name: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid profile"):
        load_profile("anime", tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        """
name: anime
unexpected: true
image_gen:
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: default
  tid: 1
""",
        """
name: anime
image_gen:
  prompt_template: "{topic}"
  unexpected: true
video_gen: {}
upload:
  account: default
  tid: 1
""",
        """
name: anime
image_gen:
  prompt_template: "{topic}"
video_gen:
  unexpected: true
upload:
  account: default
  tid: 1
""",
        """
name: anime
image_gen:
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: default
  tid: 1
  unexpected: true
""",
    ],
)
def test_load_profile_rejects_unexpected_fields(tmp_path: Path, payload: str) -> None:
    (tmp_path / "anime.yaml").write_text(payload, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_profile("anime", tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        """
name: anime
image_gen:
  count: 0
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: default
  tid: 1
""",
        """
name: anime
image_gen:
  prompt_template: ""
video_gen: {}
upload:
  account: default
  tid: 1
""",
        """
name: anime
image_gen:
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: ""
  tid: 1
""",
        """
name: anime
image_gen:
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: default
  tid: 0
""",
        """
name: anime
image_gen:
  prompt_template: "{topic}"
video_gen: {}
upload:
  account: default
  tid: 1
  tags:
    - tag-00
    - tag-01
    - tag-02
    - tag-03
    - tag-04
    - tag-05
    - tag-06
    - tag-07
    - tag-08
    - tag-09
    - tag-10
    - tag-11
    - tag-12
    - tag-13
    - tag-14
    - tag-15
    - tag-16
    - tag-17
    - tag-18
    - tag-19
    - tag-20
""",
    ],
)
def test_load_profile_rejects_unsafe_boundaries(tmp_path: Path, payload: str) -> None:
    (tmp_path / "anime.yaml").write_text(payload, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_profile("anime", tmp_path)
