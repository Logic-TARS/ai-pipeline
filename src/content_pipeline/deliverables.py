from __future__ import annotations

import os
import shutil
from pathlib import Path

__all__ = ["export_deliverables", "materialize_job_artifacts"]


def materialize_job_artifacts(job_dir: Path, files: dict[str, Path]) -> dict[str, Path]:
    """Make tool outputs durable inside the job before external task cleanup."""
    job_root = job_dir.expanduser().resolve()
    materialized: dict[str, Path] = {}
    for relative_name, source in files.items():
        relative = _safe_relative_path(relative_name)
        resolved_source = source.expanduser().resolve(strict=True)
        if not resolved_source.is_file():
            raise ValueError(f"job artifact source is not a file: {source}")
        target = job_root / relative
        if resolved_source != target:
            target.parent.mkdir(parents=True, exist_ok=True)
            _link_or_copy(resolved_source, target)
        materialized[relative_name] = target
    return materialized


def export_deliverables(
    *,
    data_dir: Path,
    job_dir: Path,
    pipeline: str,
    key: str,
    files: dict[str, Path],
    title: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
) -> tuple[Path, list[Path], Path | None]:
    """Export validated job-local artifacts into the single operator-facing tree."""
    pipeline = _safe_component(pipeline, "pipeline")
    key = _safe_component(key, "delivery key")
    job_root = job_dir.resolve()
    sources = dict(files)
    metadata_path: Path | None = None
    if title is not None:
        metadata_path = job_root / "publish_metadata.txt"
        _atomic_write(
            metadata_path,
            f"标题：\n{title.strip()}\n\n描述：\n{description.strip()}\n\n标签：\n"
            + " ".join(f"#{tag.lstrip('#')}" for tag in tags or [])
            + "\n",
        )
        sources["publish_metadata.txt"] = metadata_path

    delivery_dir = data_dir.expanduser().resolve() / "deliverables" / pipeline / key
    exported: list[Path] = []
    for relative_name, source in sources.items():
        relative = _safe_relative_path(relative_name)
        resolved_source = source.expanduser().resolve(strict=True)
        try:
            resolved_source.relative_to(job_root)
        except ValueError as exc:
            raise ValueError(f"delivery source must stay inside the job directory: {source}") from exc
        if not resolved_source.is_file():
            raise ValueError(f"delivery source is not a file: {source}")
        target = delivery_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _link_or_copy(resolved_source, target)
        exported.append(target)
    return delivery_dir, exported, metadata_path


def _safe_component(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or Path(normalized).name != normalized or normalized in {".", ".."}:
        raise ValueError(f"invalid {label}: {value}")
    return normalized


def _safe_relative_path(value: str) -> Path:
    relative = Path(value)
    if not value.strip() or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid delivery path: {value}")
    return relative


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _link_or_copy(source: Path, target: Path) -> None:
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)
    temporary.replace(target)
