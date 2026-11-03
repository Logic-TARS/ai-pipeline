from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = ["MptCleanupReport", "cleanup_mpt_tasks"]


@dataclass(frozen=True)
class MptCleanupReport:
    applied: bool
    candidates: tuple[Path, ...]
    total_size: int
    failures: tuple[tuple[Path, str], ...] = ()


def cleanup_mpt_tasks(
    mpt_dir: Path,
    *,
    older_than_days: int,
    protected: set[Path] | None = None,
    apply: bool = False,
) -> MptCleanupReport:
    if older_than_days < 1:
        raise ValueError("older_than_days must be a positive integer")
    tasks_dir = mpt_dir.expanduser().resolve() / "storage" / "tasks"
    if not tasks_dir.is_dir():
        return MptCleanupReport(applied=apply, candidates=(), total_size=0)
    protected_paths = {path.expanduser().resolve() for path in protected or set()}
    cutoff = time.time() - older_than_days * 86400
    candidates: list[Path] = []
    for path in sorted(tasks_dir.iterdir()):
        if path.is_symlink() or not path.is_dir() or path.resolve() in protected_paths:
            continue
        try:
            owned = _is_ai_pipeline_task(path)
            latest_mtime = _latest_mtime(path)
        except OSError:
            continue
        if not owned or latest_mtime >= cutoff:
            continue
        candidates.append(path)
    total_size = sum(_directory_size(path) for path in candidates)
    failures: list[tuple[Path, str]] = []
    if apply:
        for path in candidates:
            try:
                shutil.rmtree(path)
            except OSError as exc:
                failures.append((path, str(exc)))
    return MptCleanupReport(apply, tuple(candidates), total_size, tuple(failures))


def _is_ai_pipeline_task(path: Path) -> bool:
    if (path / "ai-pipeline-manifest.json").is_file() or (path / "ai-popline-manifest.json").is_file():
        return True
    script_path = path / "script.json"
    if not script_path.is_file() or script_path.stat().st_size > 2 * 1024 * 1024:
        return False
    try:
        content = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "ai-pipeline" in content or "ai-popline" in content


def _latest_mtime(path: Path) -> float:
    values = [path.stat().st_mtime]
    for name in ("final-1.mp4", "script.json", "ai-pipeline-manifest.json", "ai-popline-manifest.json"):
        candidate = path / name
        if candidate.is_file():
            values.append(candidate.stat().st_mtime)
    return max(values)


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total
