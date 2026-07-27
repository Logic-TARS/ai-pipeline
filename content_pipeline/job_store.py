from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import ArtifactSet, JobSnapshot, JobStatus, PipelineStep, RouteResult, TaskInput


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, data_dir: Path):
        self.jobs_dir = data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

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
        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")

    def event(self, task_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
        record = {"ts": utc_now(), "event": event, "payload": payload or {}}
        with self.events_path(task_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

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
