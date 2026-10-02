"""Pipeline registry with decorator-based registration.

Pipeline functions may use either the new ``PipelineContext`` signature
or the legacy five-argument ``(task_id, snapshot, artifacts, store, settings)``
signature.  The registry wraps legacy functions automatically.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from content_pipeline.job_store import JobStore
from content_pipeline.models import ArtifactSet, JobSnapshot, RouteResult
from content_pipeline.settings import Settings


@dataclass
class PipelineContext:
    """Context passed to every pipeline function."""

    task_id: str
    snapshot: JobSnapshot
    route: RouteResult
    artifacts: ArtifactSet
    store: JobStore
    settings: Settings


@dataclass
class PipelineMeta:
    """Metadata describing a registered pipeline."""

    content_type: str
    description: str
    required_params: list[str]
    external_tools: list[str]
    publish_targets: list[str]


PipelineFunc = Callable[[PipelineContext], None]

PIPELINE_REGISTRY: dict[str, PipelineFunc] = {}
PIPELINE_METADATA: dict[str, PipelineMeta] = {}

__all__ = [
    "PIPELINE_METADATA",
    "PIPELINE_REGISTRY",
    "PipelineContext",
    "PipelineFunc",
    "PipelineMeta",
    "get_pipeline",
    "get_pipeline_meta",
    "list_pipelines",
    "register",
]


def _uses_pipeline_context(fn: Callable) -> bool:
    """Return True if *fn* accepts a single PipelineContext argument."""
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        return len(params) == 1 and params[0].name == "ctx"
    except (ValueError, TypeError):
        return False


def register(content_type: str, meta: PipelineMeta | None = None):
    """Decorator to register a pipeline function.

    Legacy functions that accept ``(task_id, snapshot, artifacts, store, settings)``
    are automatically wrapped to receive a ``PipelineContext``.
    """

    def decorator(fn):
        if _uses_pipeline_context(fn):
            wrapped = fn
        else:

            def wrapped(ctx: PipelineContext) -> None:
                return fn(
                    task_id=ctx.task_id,
                    snapshot=ctx.snapshot,
                    artifacts=ctx.artifacts,
                    store=ctx.store,
                    settings=ctx.settings,
                )

            wrapped.__name__ = fn.__name__
            wrapped.__doc__ = fn.__doc__

        PIPELINE_REGISTRY[content_type] = wrapped
        if meta is not None:
            PIPELINE_METADATA[content_type] = meta
        return fn

    return decorator


def get_pipeline(content_type: str) -> PipelineFunc | None:
    """Look up a registered pipeline by content type."""
    return PIPELINE_REGISTRY.get(content_type)


def get_pipeline_meta(content_type: str) -> PipelineMeta | None:
    """Look up pipeline metadata by content type."""
    return PIPELINE_METADATA.get(content_type)


def list_pipelines() -> list[PipelineMeta]:
    """Return metadata for all registered pipelines."""
    return list(PIPELINE_METADATA.values())
