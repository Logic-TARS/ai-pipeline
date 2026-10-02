from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .job_store import utc_now
from .models import TaskInput

__all__ = [
    "ScheduleRunner",
    "ScheduleStore",
    "ScheduledJob",
    "compute_next_run",
]

_SCHEDULE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _local_now() -> datetime:
    return datetime.now().astimezone()


class ScheduledJob(BaseModel):
    """A recurring task definition. Publishing is opt-in per schedule."""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=120)
    task: TaskInput
    frequency: Literal["daily", "weekly"]
    time_of_day: str = Field(pattern=_TIME_PATTERN)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    enabled: bool = True
    created_at: str
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_task_id: str | None = None
    last_error: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, values: list[int]) -> list[int]:
        result: list[int] = []
        for value in values:
            if value < 0 or value > 6:
                raise ValueError("weekdays must be integers between 0 (Monday) and 6 (Sunday)")
            if value not in result:
                result.append(value)
        return sorted(result)

    @model_validator(mode="after")
    def validate_consistency(self) -> ScheduledJob:
        if self.frequency == "weekly" and not self.weekdays:
            raise ValueError("weekly schedules require at least one weekday")
        if self.frequency == "daily":
            self.weekdays = []
        return self


def compute_next_run(schedule: ScheduledJob, now: datetime) -> datetime:
    """Return the next local run time strictly after *now*."""
    hour, minute = (int(part) for part in schedule.time_of_day.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if schedule.frequency == "daily":
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    for offset in range(8):
        day = candidate + timedelta(days=offset)
        if day.weekday() in schedule.weekdays and day > now:
            return day
    raise ValueError("weekly schedules require at least one weekday")


class ScheduleStore:
    """Persists schedule definitions as JSON files under data_dir/schedules."""

    def __init__(self, data_dir: Path):
        self.schedules_dir = data_dir / "schedules"
        self.schedules_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, schedule_id: str) -> Path:
        if not _SCHEDULE_ID_PATTERN.fullmatch(schedule_id):
            raise FileNotFoundError(f"schedule not found: {schedule_id}")
        return self.schedules_dir / f"{schedule_id}.json"

    def create(
        self,
        *,
        name: str,
        task: TaskInput,
        frequency: str,
        time_of_day: str,
        weekdays: list[int] | None = None,
        enabled: bool = True,
    ) -> ScheduledJob:
        schedule = ScheduledJob(
            schedule_id=uuid4().hex,
            name=name,
            task=task,
            frequency=frequency,
            time_of_day=time_of_day,
            weekdays=weekdays or [],
            enabled=enabled,
            created_at=utc_now(),
        )
        schedule.next_run_at = compute_next_run(schedule, _local_now()).isoformat() if enabled else None
        self.save(schedule)
        return schedule

    def get(self, schedule_id: str) -> ScheduledJob:
        with self._lock:
            path = self._path(schedule_id)
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(f"schedule not found: {schedule_id}")
            return ScheduledJob.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, schedule: ScheduledJob) -> None:
        with self._lock:
            path = self._path(schedule.schedule_id)
            if path.is_symlink():
                raise FileNotFoundError(f"schedule not found: {schedule.schedule_id}")
            data = schedule.model_dump(mode="json")
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(path)

    def list(self) -> list[ScheduledJob]:
        schedules: list[ScheduledJob] = []
        for path in sorted(self.schedules_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                schedules.append(ScheduledJob.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        schedules.sort(key=lambda item: item.created_at, reverse=True)
        return schedules

    def delete(self, schedule_id: str) -> None:
        with self._lock:
            path = self._path(schedule_id)
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(f"schedule not found: {schedule_id}")
            path.unlink()


class ScheduleRunner:
    """Background loop that submits due schedules to the orchestrator."""

    def __init__(
        self,
        store: ScheduleStore,
        submit_run,
        *,
        interval_seconds: float = 30.0,
    ):
        self.store = store
        self._submit_run = submit_run
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="schedule-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.run_due()

    def run_due(self, now: datetime | None = None) -> list[str]:
        """Run every enabled schedule whose next_run_at has passed. Returns new task ids."""
        moment = now or _local_now()
        submitted: list[str] = []
        for schedule in self.store.list():
            if not schedule.enabled:
                continue
            due = self._due_time(schedule, moment)
            if due is None or due > moment:
                continue
            try:
                task_id = self._submit_run(schedule.task)
                schedule.last_task_id = task_id
                schedule.last_error = None
                submitted.append(task_id)
            except Exception as exc:  # keep the runner alive on submission failures
                schedule.last_error = str(exc)[:200]
            schedule.last_run_at = utc_now()
            schedule.next_run_at = compute_next_run(schedule, moment).isoformat()
            self.store.save(schedule)
        return submitted

    def _due_time(self, schedule: ScheduledJob, now: datetime) -> datetime | None:
        if not schedule.next_run_at:
            schedule.next_run_at = compute_next_run(schedule, now).isoformat()
            self.store.save(schedule)
        try:
            due = datetime.fromisoformat(schedule.next_run_at)
        except ValueError:
            due = compute_next_run(schedule, now)
            schedule.next_run_at = due.isoformat()
            self.store.save(schedule)
        if due.tzinfo is None:
            due = due.astimezone()
        return due

    def describe(self, schedule: ScheduledJob) -> dict[str, Any]:
        """User-facing summary for API responses."""
        return {
            "schedule_id": schedule.schedule_id,
            "name": schedule.name,
            "frequency": schedule.frequency,
            "time_of_day": schedule.time_of_day,
            "weekdays": schedule.weekdays,
            "weekday_labels": [WEEKDAY_LABELS[day] for day in schedule.weekdays],
            "enabled": schedule.enabled,
            "content_type": schedule.task.content_type or None,
            "description": schedule.task.description,
            "topic": schedule.task.topic,
            "publish": schedule.task.publish,
            "params": schedule.task.params,
            "created_at": schedule.created_at,
            "next_run_at": schedule.next_run_at,
            "last_run_at": schedule.last_run_at,
            "last_task_id": schedule.last_task_id,
            "last_error": schedule.last_error,
        }
