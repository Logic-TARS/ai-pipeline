from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import ArtifactSet, JobSnapshot, JobStatus, PipelineStep, RouteResult, TaskInput

STORE_VERSION = 1
"""Schema version written into every status.json. Increment on breaking changes."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, data_dir: Path):
        self.jobs_dir = data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, task: TaskInput) -> JobSnapshot:
        task_id = uuid4().hex
        job_dir = self.job_dir(task_id)
        (job_dir / "images").mkdir(parents=True)
        (job_dir / "video").mkdir()
        snapshot = JobSnapshot(
            task_id=task_id,
            status=JobStatus.QUEUED,
            task=task,
        )
        self.save(snapshot)
        self.event(task_id, "job_created", {"task": task.model_dump(mode="json")})
        return snapshot

    def job_dir(self, task_id: str) -> Path:
        return self.jobs_dir / task_id

    def status_path(self, task_id: str) -> Path:
        return self.job_dir(task_id) / "status.json"

    def events_path(self, task_id: str) -> Path:
        return self.job_dir(task_id) / "events.jsonl"

    def get(self, task_id: str) -> JobSnapshot:
        raw = self.status_path(task_id).read_text(encoding="utf-8")
        return JobSnapshot.model_validate_json(raw)

    def save(self, snapshot: JobSnapshot) -> None:
        path = self.status_path(snapshot.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = snapshot.model_dump(mode="json")
        data["store_version"] = STORE_VERSION
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def event(self, task_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": utc_now(),
            "event": event,
            "payload": payload or {},
        }
        with self.events_path(task_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str, step: PipelineStep) -> JobSnapshot:
        snapshot = self.get(task_id)
        snapshot.status = JobStatus.RUNNING
        snapshot.current_step = step
        snapshot.error = None
        self.save(snapshot)
        self.event(task_id, "step_started", {"step": step.value})
        return snapshot

    def set_route(self, task_id: str, route: RouteResult) -> None:
        snapshot = self.get(task_id)
        snapshot.route = route
        self.save(snapshot)
        self.event(task_id, "route_resolved", route.model_dump(mode="json"))

    def set_artifacts(self, task_id: str, artifacts: ArtifactSet) -> None:
        snapshot = self.get(task_id)
        snapshot.artifacts = artifacts
        self.save(snapshot)

    def finish(self, task_id: str, status: JobStatus, error: str | None = None) -> None:
        snapshot = self.get(task_id)
        snapshot.status = status
        snapshot.current_step = (
            PipelineStep.COMPLETE if status in {JobStatus.SUCCEEDED, JobStatus.PARTIAL} else snapshot.current_step
        )
        snapshot.error = error
        self.save(snapshot)
        self.event(task_id, "job_finished", {"status": status.value, "error": error})

    # ------------------------------------------------------------------
    # Listing & cleanup
    # ------------------------------------------------------------------

    def list_jobs(
        self,
        status: JobStatus | None = None,
        content_type: str | None = None,
        limit: int = 50,
    ) -> list[JobSnapshot]:
        """Return recent job snapshots, optionally filtered. Newest first."""
        jobs: list[JobSnapshot] = []
        job_dirs = [path for path in self.jobs_dir.iterdir() if path.is_dir()]
        job_dirs.sort(
            key=lambda path: (path / "status.json").stat().st_mtime if (path / "status.json").exists() else 0,
            reverse=True,
        )
        for job_dir in job_dirs:
            if not job_dir.is_dir():
                continue
            status_path = job_dir / "status.json"
            if not status_path.exists():
                continue
            try:
                snapshot = JobSnapshot.model_validate_json(status_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if status is not None and snapshot.status != status:
                continue
            if content_type is not None and snapshot.route and snapshot.route.content_type != content_type:
                continue
            jobs.append(snapshot)
            if len(jobs) >= limit:
                break
        return jobs

    def cleanup_old_jobs(self, max_age_days: int = 30) -> int:
        """Delete jobs older than *max_age_days*. Returns count of removed jobs."""
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for job_dir in self.jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if not status_file.exists():
                continue
            try:
                mtime = status_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                _rmtree(job_dir)
                removed += 1
        return removed


def _rmtree(path: Path) -> None:
    """Remove a directory tree. Missing path is a no-op."""
    if not path.exists():
        return
    for child in sorted(path.iterdir(), key=lambda p: p.is_dir(), reverse=True):
        if child.is_dir() and not child.is_symlink():
            _rmtree(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()
