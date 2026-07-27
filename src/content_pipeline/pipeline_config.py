from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from content_pipeline.models import RouteResult
from content_pipeline.settings import Settings


def apply_pipeline_defaults(route: RouteResult, *, settings: Settings, task_id: str) -> RouteResult:
    """Merge optional YAML defaults into a routed task.

    Defaults are intentionally opt-in.  The configured YAML file must exist and
    contain ``enabled: true`` before it affects any task.  Explicit task params
    always win over YAML defaults.
    """
    payload = load_pipeline_defaults(settings.pipeline_defaults_file)
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


def load_pipeline_defaults(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


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
