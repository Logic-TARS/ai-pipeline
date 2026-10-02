from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from content_pipeline.models import JobSnapshot

__all__ = ["RegisteredArtifact", "registered_artifacts"]

_CONTROL_FILE_NAMES = {"status.json", "events.jsonl"}


@dataclass(frozen=True)
class RegisteredArtifact:
    artifact_id: str
    path: Path
    relative_path: str
    media_type: str
    size: int


def registered_artifacts(snapshot: JobSnapshot, job_dir: Path) -> dict[str, RegisteredArtifact]:
    """Return existing artifact files that resolve inside this job directory."""
    if job_dir.is_symlink() or not job_dir.is_dir():
        return {}
    root = job_dir.resolve()
    result: dict[str, RegisteredArtifact] = {}
    for candidate in _iter_paths(snapshot.artifacts):
        try:
            resolved = candidate.expanduser().resolve(strict=True)
            relative = resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        if not resolved.is_file() or resolved.name in _CONTROL_FILE_NAMES:
            continue
        relative_path = relative.as_posix()
        artifact_id = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
        media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        result[artifact_id] = RegisteredArtifact(
            artifact_id=artifact_id,
            path=resolved,
            relative_path=relative_path,
            media_type=media_type,
            size=resolved.stat().st_size,
        )
    return result


def _iter_paths(value: Any):
    if isinstance(value, Path):
        yield value
    elif isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _iter_paths(getattr(value, field_name))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_paths(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_paths(item)
