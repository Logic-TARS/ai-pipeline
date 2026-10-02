from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_pipeline.api.app import create_app
from content_pipeline.models import TaskInput
from content_pipeline.scheduler import (
    ScheduledJob,
    ScheduleRunner,
    ScheduleStore,
    compute_next_run,
)
from content_pipeline.settings import Settings

ADMIN_TOKEN = "admin-" + "a" * 32
API_TOKEN = "api-" + "b" * 32
SESSION_SECRET = "session-" + "c" * 32


def _settings(tmp_path: Path, **overrides) -> Settings:
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    values = {
        "data_dir": tmp_path / "output",
        "profiles_dir": profiles,
        "web_allowed_hosts": "testserver",
        "web_allowed_origins": "http://testserver",
        "web_auth_required": True,
        "web_admin_token": ADMIN_TOKEN,
        "web_api_token": API_TOKEN,
        "web_session_secret": SESSION_SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _task(**overrides) -> TaskInput:
    values = {
        "description": "每日 AI 简报",
        "content_type": "anime",
        "publish": False,
        "params": {"script": "第一幕：定时运行。", "dry_run": True},
    }
    values.update(overrides)
    return TaskInput(**values)


def _schedule(schedule_id: str = "a" * 32, **overrides) -> ScheduledJob:
    values = {
        "schedule_id": schedule_id,
        "name": "每日任务",
        "task": _task(),
        "frequency": "daily",
        "time_of_day": "08:00",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    values.update(overrides)
    return ScheduledJob(**values)


def test_compute_next_run_daily_rolls_to_tomorrow_after_time_passed() -> None:
    schedule = _schedule(time_of_day="08:00")
    now = datetime(2026, 1, 10, 9, 30).astimezone()
    nxt = compute_next_run(schedule, now)
    assert (nxt.hour, nxt.minute) == (8, 0)
    assert nxt.date() == (now + timedelta(days=1)).date()


def test_compute_next_run_daily_stays_today_before_time() -> None:
    schedule = _schedule(time_of_day="08:00")
    now = datetime(2026, 1, 10, 6, 0).astimezone()
    nxt = compute_next_run(schedule, now)
    assert nxt.date() == now.date()
    assert (nxt.hour, nxt.minute) == (8, 0)


def test_compute_next_run_weekly_picks_next_matching_weekday() -> None:
    schedule = _schedule(frequency="weekly", time_of_day="08:00", weekdays=[0])  # Monday
    friday = datetime(2026, 1, 9, 9, 0).astimezone()  # 2026-01-09 is a Friday
    nxt = compute_next_run(schedule, friday)
    assert nxt.weekday() == 0
    assert nxt > friday
    assert (nxt.hour, nxt.minute) == (8, 0)


def test_compute_next_run_weekly_same_day_after_time_rolls_a_week() -> None:
    schedule = _schedule(frequency="weekly", time_of_day="08:00", weekdays=[5])  # Saturday
    saturday = datetime(2026, 1, 10, 9, 0).astimezone()  # 2026-01-10 is a Saturday
    nxt = compute_next_run(schedule, saturday)
    assert nxt.weekday() == 5
    assert (nxt.date() - saturday.date()).days == 7


def test_weekly_schedule_requires_weekday() -> None:
    with pytest.raises(ValueError):
        _schedule(frequency="weekly", weekdays=[])


def test_scheduled_task_may_publish() -> None:
    schedule = _schedule(task=_task(publish=True))
    assert schedule.task.publish is True


def test_schedule_store_crud_roundtrip(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    schedule = store.create(
        name="每日 AI 简报",
        task=_task(),
        frequency="daily",
        time_of_day="08:00",
    )
    assert schedule.next_run_at is not None

    loaded = store.get(schedule.schedule_id)
    assert loaded.name == "每日 AI 简报"
    assert [item.schedule_id for item in store.list()] == [schedule.schedule_id]

    store.delete(schedule.schedule_id)
    assert store.list() == []
    with pytest.raises(FileNotFoundError):
        store.get(schedule.schedule_id)


def test_schedule_runner_submits_due_schedules(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    due = store.create(name="到期任务", task=_task(), frequency="daily", time_of_day="08:00")
    future = store.create(name="未到期任务", task=_task(), frequency="daily", time_of_day="08:00")
    past = datetime.now().astimezone() - timedelta(minutes=5)
    due.next_run_at = past.isoformat()
    future.next_run_at = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
    store.save(due)
    store.save(future)

    submitted: list[TaskInput] = []
    runner = ScheduleRunner(store, lambda task: submitted.append(task) or "task-1")
    assert runner.run_due() == ["task-1"]

    updated = store.get(due.schedule_id)
    assert updated.last_task_id == "task-1"
    assert datetime.fromisoformat(updated.next_run_at) > datetime.now().astimezone()
    assert store.get(future.schedule_id).last_task_id is None


def test_schedule_runner_skips_disabled(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    schedule = store.create(name="停用任务", task=_task(), frequency="daily", time_of_day="08:00", enabled=False)
    assert schedule.next_run_at is None
    submitted: list[TaskInput] = []
    runner = ScheduleRunner(store, lambda task: submitted.append(task) or "task-1")
    assert runner.run_due() == []
    assert submitted == []


def test_schedules_api_crud(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.orchestrator.run = lambda _task_id: None
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        payload = {
            "name": "每日 AI 简报",
            "frequency": "daily",
            "time_of_day": "08:00",
            "task": {
                "description": "每日 AI 简报",
                "content_type": "anime",
                "params": {"script": "第一幕：定时运行。", "dry_run": True},
            },
        }
        created = client.post("/schedules", headers=_bearer(), json=payload)
        assert created.status_code == 201
        schedule_id = created.json()["schedule_id"]
        assert created.json()["next_run_at"] is not None

        listed = client.get("/schedules", headers=_bearer())
        assert listed.status_code == 200
        assert [item["schedule_id"] for item in listed.json()["schedules"]] == [schedule_id]

        disabled = client.patch(f"/schedules/{schedule_id}", headers=_bearer(), json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False
        assert disabled.json()["next_run_at"] is None

        enabled = client.patch(f"/schedules/{schedule_id}", headers=_bearer(), json={"enabled": True})
        assert enabled.status_code == 200
        assert enabled.json()["next_run_at"] is not None

        run = client.post(f"/schedules/{schedule_id}/run", headers=_bearer())
        assert run.status_code == 202
        assert run.json()["status"] == "queued"

        deleted = client.delete(f"/schedules/{schedule_id}", headers=_bearer())
        assert deleted.status_code == 200
        assert client.get("/schedules", headers=_bearer()).json() == {"schedules": []}
        assert client.delete(f"/schedules/{schedule_id}", headers=_bearer()).status_code == 404


def test_schedules_api_update_task(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, web_publish_enabled=True))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        payload = {
            "name": "每日 AI 简报",
            "frequency": "daily",
            "time_of_day": "08:00",
            "task": {
                "description": "每日 AI 简报",
                "content_type": "anime",
                "params": {"script": "第一幕：定时运行。", "dry_run": True},
            },
        }
        created = client.post("/schedules", headers=_bearer(), json=payload)
        assert created.status_code == 201
        schedule_id = created.json()["schedule_id"]

        updated = client.patch(
            f"/schedules/{schedule_id}",
            headers=_bearer(),
            json={
                "task": {
                    "description": "改版后的金融简报",
                    "content_type": "anime",
                    "publish": True,
                    "params": {"script": "第一幕：改版后的内容。", "dry_run": True},
                }
            },
        )
        assert updated.status_code == 200
        assert updated.json()["description"] == "改版后的金融简报"
        assert updated.json()["publish"] is True
        assert updated.json()["params"]["script"] == "第一幕：改版后的内容。"


def test_schedules_api_update_rejects_publish_when_disabled(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, web_publish_enabled=False))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        payload = {
            "name": "每日 AI 简报",
            "frequency": "daily",
            "time_of_day": "08:00",
            "task": {
                "description": "每日 AI 简报",
                "content_type": "anime",
                "params": {"script": "第一幕：定时运行。", "dry_run": True},
            },
        }
        created = client.post("/schedules", headers=_bearer(), json=payload)
        assert created.status_code == 201
        schedule_id = created.json()["schedule_id"]

        updated = client.patch(
            f"/schedules/{schedule_id}",
            headers=_bearer(),
            json={
                "task": {
                    "description": "每日 AI 简报",
                    "content_type": "anime",
                    "publish": True,
                    "params": {"script": "第一幕：定时运行。", "dry_run": True},
                }
            },
        )
        assert updated.status_code == 403


def test_schedules_api_allows_publish_when_web_publish_enabled(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, web_publish_enabled=True))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        payload = {
            "name": "定时发布",
            "frequency": "daily",
            "time_of_day": "08:00",
            "task": {
                "description": "每日 AI 简报",
                "content_type": "anime",
                "publish": True,
                "params": {"script": "第一幕：定时运行。", "dry_run": True},
            },
        }
        response = client.post("/schedules", headers=_bearer(), json=payload)
    assert response.status_code == 201
    assert response.json()["publish"] is True


def test_schedules_api_rejects_publish_when_web_publish_disabled(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, web_publish_enabled=False))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        payload = {
            "name": "尝试发布",
            "frequency": "daily",
            "time_of_day": "08:00",
            "task": {
                "description": "每日 AI 简报",
                "content_type": "anime",
                "publish": True,
                "params": {"script": "第一幕：定时运行。", "dry_run": True},
            },
        }
        response = client.post("/schedules", headers=_bearer(), json=payload)
    assert response.status_code == 403


def test_schedules_api_requires_authentication(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        assert client.get("/schedules").status_code == 401
