from importlib import resources
from pathlib import Path

import pytest
from pydantic import BaseModel

from content_pipeline.errors import ConfigError
from content_pipeline.models import RouteResult
from content_pipeline.pipeline_config import apply_pipeline_defaults, load_pipeline_defaults
from content_pipeline.settings import Settings
from content_pipeline.task_validation import PARAM_MODELS


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


def test_load_pipeline_defaults_reports_invalid_yaml(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.defaults.yaml"
    config.write_text("enabled: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid pipeline defaults"):
        load_pipeline_defaults(config)


def test_packaged_pipeline_defaults_are_disabled_by_default() -> None:
    payload = load_pipeline_defaults(Path("config/pipeline.defaults.yaml"))

    assert payload["enabled"] is False


def test_packaged_pipeline_defaults_resource_matches_root_config() -> None:
    root_config = Path("config/pipeline.defaults.yaml").read_text(encoding="utf-8")
    packaged_config = (
        resources.files("content_pipeline.config").joinpath("pipeline.defaults.yaml").read_text(encoding="utf-8")
    )

    assert packaged_config == root_config


def test_default_pipeline_defaults_path_falls_back_to_packaged_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    payload = load_pipeline_defaults(Path("config/pipeline.defaults.yaml"))

    assert payload["enabled"] is False
    assert isinstance(payload.get("pipelines"), dict)


def test_packaged_pipeline_defaults_only_reference_known_pipelines_and_params() -> None:
    payload = load_pipeline_defaults(Path("config/pipeline.defaults.yaml"))
    pipelines = payload.get("pipelines")

    assert isinstance(pipelines, dict)
    assert set(pipelines) <= set(PARAM_MODELS)

    invalid_params: list[str] = []
    for content_type, pipeline_config in pipelines.items():
        assert isinstance(pipeline_config, dict)
        params = pipeline_config.get("params", {})
        assert isinstance(params, dict)
        model = PARAM_MODELS[content_type]
        known_fields = _model_field_names(model)
        for name in params:
            if name not in known_fields:
                invalid_params.append(f"{content_type}.{name}")

    assert invalid_params == []


def test_packaged_pipeline_default_values_validate_against_param_models() -> None:
    payload = load_pipeline_defaults(Path("config/pipeline.defaults.yaml"))
    pipelines = payload.get("pipelines")
    assert isinstance(pipelines, dict)

    invalid_defaults: list[str] = []
    for content_type, pipeline_config in pipelines.items():
        assert isinstance(pipeline_config, dict)
        params = pipeline_config.get("params", {})
        assert isinstance(params, dict)
        model = PARAM_MODELS[content_type]
        try:
            model.model_validate({**_minimal_params_for(content_type), **params})
        except ValueError as exc:
            invalid_defaults.append(f"{content_type}: {exc}")

    assert invalid_defaults == []


def test_configuration_docs_cover_packaged_pipeline_default_contract() -> None:
    docs = Path("docs/configuration.md").read_text(encoding="utf-8")
    payload = load_pipeline_defaults(Path("config/pipeline.defaults.yaml"))
    pipelines = payload.get("pipelines")
    assert isinstance(pipelines, dict)

    assert "config/pipeline.defaults.yaml" in docs
    assert "enabled: false" in docs
    for placeholder in ("{data_dir}", "{task_id}", "{content_type}", "{topic}"):
        assert placeholder in docs
    for content_type in pipelines:
        assert f"`{content_type}`" in docs


def _minimal_params_for(content_type: str) -> dict[str, object]:
    return {
        "anime": {"script": "minimal script"},
        "ai_art": {"source_dir": ".", "process_name": "process", "title": "title"},
        "xhs_image_note": {"source_dir": ".", "process_name": "process"},
        "grouped_anime": {"source_dir": "."},
        "japanese": {"source_dir": "."},
        "finance": {},
        "ai_briefing": {},
        "script_video": {"title": "title", "script": "x" * 300},
    }[content_type]


def _model_field_names(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields)
