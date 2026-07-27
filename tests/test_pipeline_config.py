from pathlib import Path

from content_pipeline.models import RouteResult
from content_pipeline.pipeline_config import apply_pipeline_defaults
from content_pipeline.settings import Settings


def test_disabled_pipeline_defaults_do_not_change_route(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.defaults.yaml"
    config.write_text(
        """
enabled: false
pipelines:
  japanese:
    params:
      output_dir: should-not-apply
""",
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "output", pipeline_defaults_file=config)
    route = RouteResult(content_type="japanese", topic="topic", params={"source_dir": "input"})

    merged = apply_pipeline_defaults(route, settings=settings, task_id="abc")

    assert merged.params == {"source_dir": "input"}


def test_pipeline_defaults_merge_and_task_params_win(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.defaults.yaml"
    config.write_text(
        """
enabled: true
pipelines:
  japanese:
    params:
      source_dir: default-input
      output_dir: "{data_dir}/japanese/{task_id}"
      image_prompt: default-prompt
""",
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "output", pipeline_defaults_file=config)
    route = RouteResult(
        content_type="japanese",
        topic="topic",
        params={"source_dir": "task-input", "target_gem_url": "https://example.invalid"},
    )

    merged = apply_pipeline_defaults(route, settings=settings, task_id="abc")

    assert merged.params["source_dir"] == "task-input"
    assert merged.params["target_gem_url"] == "https://example.invalid"
    assert merged.params["image_prompt"] == "default-prompt"
    assert merged.params["output_dir"].endswith("output/japanese/abc")
