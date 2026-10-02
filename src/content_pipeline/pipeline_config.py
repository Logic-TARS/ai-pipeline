from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from content_pipeline.errors import ConfigError
from content_pipeline.models import RouteResult, TaskInput
from content_pipeline.settings import Settings
from content_pipeline.task_validation import validate_task_params

__all__ = [
    "apply_pipeline_defaults",
    "load_effective_pipeline_defaults",
    "load_pipeline_defaults",
    "save_pipeline_defaults_override",
]


def apply_pipeline_defaults(route: RouteResult, *, settings: Settings, task_id: str) -> RouteResult:
    """Merge optional defaults into a routed task.

    Defaults are intentionally opt-in.  ``enabled: true`` must be set (YAML or
    the saved override) before they affect any task.  Explicit task params
    always win over defaults.
    """
    payload = load_effective_pipeline_defaults(settings)
    if not payload.get("enabled"):
        return route

    pipelines = payload.get("pipelines") or {}
    if not isinstance(pipelines, dict):
        return route
    pipeline_config = pipelines.get(route.content_type) or {}
    if not isinstance(pipeline_config, dict):
        return route

    default_params = pipeline_config.get("params") or {}
    if not isinstance(default_params, dict):
        return route

    context = {
        "content_type": route.content_type,
        "data_dir": str(settings.data_dir),
        "task_id": task_id,
        "topic": route.topic,
    }
    rendered_defaults = _render_value(default_params, context)
    merged_params = {**rendered_defaults, **route.params}
    return route.model_copy(update={"params": merged_params})


def load_effective_pipeline_defaults(settings: Settings) -> dict[str, Any]:
    """YAML defaults merged with the operator override saved from the web console."""
    payload = load_pipeline_defaults(settings.pipeline_defaults_file)
    override = _load_override(settings)
    if not override:
        return payload
    merged = dict(payload)
    if "enabled" in override:
        merged["enabled"] = bool(override["enabled"])
    pipelines = dict(payload.get("pipelines") or {})
    for content_type, entry in (override.get("pipelines") or {}).items():
        pipelines[content_type] = entry
    merged["pipelines"] = pipelines
    return merged


def save_pipeline_defaults_override(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist the operator override; returns the effective defaults."""
    normalized = validate_pipeline_defaults_override(payload)
    path = _override_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_effective_pipeline_defaults(settings)


def validate_pipeline_defaults_override(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ConfigError("pipeline defaults must be a mapping")
    normalized: dict[str, Any] = {"enabled": bool(payload.get("enabled")), "pipelines": {}}
    raw_pipelines = payload.get("pipelines") or {}
    if not isinstance(raw_pipelines, dict):
        raise ConfigError("pipeline defaults 'pipelines' must be a mapping")
    for content_type, entry in raw_pipelines.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"pipeline defaults entry for {content_type} must be a mapping")
        params = entry.get("params") or {}
        if not isinstance(params, dict):
            raise ConfigError(f"pipeline params for {content_type} must be a mapping")
        content_type = str(content_type)
        try:
            validate_task_params(
                TaskInput(description="validate pipeline defaults", content_type=content_type, params=params)
            )
        except ValueError as exc:
            raise ConfigError(f"invalid pipeline params for {content_type}: {exc}") from exc
        normalized["pipelines"][content_type] = {"params": params}
    return normalized


def _override_path(settings: Settings) -> Path:
    return settings.data_dir / "pipeline_defaults_override.json"


def _load_override(settings: Settings) -> dict[str, Any]:
    path = _override_path(settings)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_pipeline_defaults(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else _packaged_defaults_text(path)
        data = yaml.safe_load(text) or {}
    except OSError as exc:
        raise ConfigError(f"cannot read pipeline defaults {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid pipeline defaults {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _packaged_defaults_text(path: Path) -> str:
    if path != Settings.model_fields["pipeline_defaults_file"].default:
        return ""
    try:
        return resources.files("content_pipeline.config").joinpath("pipeline.defaults.yaml").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        return ""


def _render_value(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        try:
            return value.format(**context)
        except (KeyError, ValueError):
            return value
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    return value
