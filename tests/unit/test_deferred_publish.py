import time
from pathlib import Path

from fastapi.testclient import TestClient

import content_pipeline.api.security as security_module
from content_pipeline.api.app import create_app
from content_pipeline.deferred_publishing import publication_summary
from content_pipeline.models import JobStatus, MediaValidation, TaskInput, VideoValidation
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
        "web_publish_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _completed_content_job(app, *, dry_run: bool = False, validated: bool = True, legacy: bool = False):
    store = app.state.orchestrator.store
    snapshot = store.create(
        TaskInput(
            description="内容工作台 · 今日金融资讯",
            content_type="script_video",
            topic="今日金融资讯",
            params={
                "title": "今日金融资讯",
                "script": "市场信息。" * 80,
                "description": "每日市场观察",
                "tags": ["金融", "市场"],
                "dry_run": dry_run,
            },
            origin=None if legacy else "content_studio",
            source_draft_id=None if legacy else "a" * 32,
            source_draft_revision=None if legacy else 2,
        )
    )
    video = store.job_dir(snapshot.task_id) / "video" / "final-1.mp4"
    video.write_bytes(b"validated-video-bytes")
    snapshot.status = JobStatus.SUCCEEDED
    snapshot.artifacts.video = video
    if validated:
        snapshot.artifacts.validation = MediaValidation(
            video=VideoValidation(
                duration_seconds=90,
                width=1080,
                height=1920,
                aspect_ratio=0.5625,
                video_codec="h264",
                audio_codec="aac",
                decoded_video_frames=2700,
                decoded_audio_frames=4000,
            )
        )
    store.save(snapshot)
    return snapshot, video


def _body(title: str = "今日金融资讯") -> dict:
    return {
        "publish_targets": [{"platform": "douyin", "account": "金融破壁人"}],
        "title": title,
        "description": "每日市场观察",
        "tags": ["金融", "市场"],
    }


def test_completed_content_job_requires_artifact_bound_confirmation_and_keeps_generation_status(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app(_settings(tmp_path))
    snapshot, video = _completed_content_job(app)
    monkeypatch.setattr(
        "content_pipeline.deferred_publishing.call_sau_target",
        lambda **_kwargs: {
            "success": True,
            "visibility": "private",
            "private_visibility_proof": "已设置为“仅自己可见”",
            "publication_proof": "视频发布成功",
        },
    )
    monkeypatch.setattr(app.state.executor, "submit", lambda fn, **kwargs: fn(**kwargs))

    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        readiness = client.get(f"/jobs/{snapshot.task_id}/publish-readiness", headers=_bearer())
        unconfirmed = client.post(f"/jobs/{snapshot.task_id}/publish", headers=_bearer(), json=_body())
        required = unconfirmed.json()["detail"]["required_confirmation"]
        changed = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": required},
            json=_body("已被修改的标题"),
        )
        accepted = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": required},
            json=_body(),
        )
        completed = client.get(f"/status/{snapshot.task_id}", headers=_bearer()).json()

    assert readiness.status_code == 200
    assert readiness.json()["eligible"] is True
    assert unconfirmed.status_code == 409
    assert required.startswith("PUBLISH:")
    assert changed.status_code == 409
    assert accepted.status_code == 202
    assert completed["status"] == "succeeded"
    assert completed["current_step"] is None
    assert completed["publication_attempts"][0]["status"] == "succeeded"
    assert completed["publication_attempts"][0]["results"]["douyin"]["success"] is True
    assert completed["publication_summary"]["state"] == "published"
    assert completed["publication_summary"]["label"] == "已发布"
    assert completed["publication_summary"]["targets"][0] == {
        "platform": "douyin",
        "account": "金融破壁人",
        "status": "published",
        "success": True,
        "visibility": "private",
        "proof": "视频发布成功",
        "error": None,
        "skipped": False,
    }
    assert video.read_bytes() == b"validated-video-bytes"
    events = app.state.orchestrator.store.events_path(snapshot.task_id).read_text(encoding="utf-8")
    assert '"event": "publish_requested"' in events
    assert '"event": "publish_started"' in events
    assert '"event": "publish_target_finished"' in events
    assert '"event": "publish_finished"' in events


def test_publish_readiness_supports_legacy_studio_job_and_rejects_unsafe_jobs(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    legacy, _ = _completed_content_job(app, legacy=True)
    dry_run, _ = _completed_content_job(app, dry_run=True)
    unvalidated, _ = _completed_content_job(app, validated=False)
    missing, missing_video = _completed_content_job(app)
    missing_video.unlink()

    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        legacy_result = client.get(f"/jobs/{legacy.task_id}/publish-readiness", headers=_bearer()).json()
        dry_result = client.get(f"/jobs/{dry_run.task_id}/publish-readiness", headers=_bearer()).json()
        validation_result = client.get(f"/jobs/{unvalidated.task_id}/publish-readiness", headers=_bearer()).json()
        missing_result = client.get(f"/jobs/{missing.task_id}/publish-readiness", headers=_bearer()).json()

    assert legacy_result["eligible"] is True
    assert legacy_result["content_studio_job"] is True
    assert dry_result["eligible"] is False
    assert any("干运行" in reason for reason in dry_result["reasons"])
    assert validation_result["eligible"] is False
    assert any("媒体校验" in reason for reason in validation_result["reasons"])
    assert missing_result["eligible"] is False
    assert any("不存在" in reason for reason in missing_result["reasons"])


def test_publish_is_blocked_when_server_guard_is_off_or_video_leaves_job_directory(tmp_path: Path) -> None:
    disabled_app = create_app(_settings(tmp_path / "disabled", web_publish_enabled=False))
    disabled, _ = _completed_content_job(disabled_app)
    with TestClient(disabled_app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        blocked = client.post(f"/jobs/{disabled.task_id}/publish", headers=_bearer(), json=_body())

    guarded_app = create_app(_settings(tmp_path / "outside"))
    guarded, _ = _completed_content_job(guarded_app)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    current = guarded_app.state.orchestrator.store.get(guarded.task_id)
    current.artifacts.video = outside
    guarded_app.state.orchestrator.store.save(current)
    with TestClient(guarded_app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        escaped = client.post(f"/jobs/{guarded.task_id}/publish", headers=_bearer(), json=_body())

    assert blocked.status_code == 403
    assert escaped.status_code == 409
    assert "受保护的任务目录" in escaped.json()["detail"]


def test_video_change_invalidates_confirmation(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    snapshot, video = _completed_content_job(app)
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        unconfirmed = client.post(f"/jobs/{snapshot.task_id}/publish", headers=_bearer(), json=_body())
        required = unconfirmed.json()["detail"]["required_confirmation"]
        video.write_bytes(b"changed-after-review")
        rejected = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": required},
            json=_body(),
        )

    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "publish_confirmation_required"
    assert rejected.json()["detail"]["required_confirmation"] != required


def test_active_publication_blocks_concurrent_attempt(tmp_path: Path, monkeypatch) -> None:
    app = create_app(_settings(tmp_path))
    snapshot, _ = _completed_content_job(app)
    queued = []
    monkeypatch.setattr(app.state.executor, "submit", lambda fn, **kwargs: queued.append((fn, kwargs)))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        first = client.post(f"/jobs/{snapshot.task_id}/publish", headers=_bearer(), json=_body())
        required = first.json()["detail"]["required_confirmation"]
        accepted = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": required},
            json=_body(),
        )
        concurrent = client.post(f"/jobs/{snapshot.task_id}/publish", headers=_bearer(), json=_body())

    assert accepted.status_code == 202
    assert len(queued) == 1
    assert concurrent.status_code == 409
    assert "正在排队或运行" in concurrent.json()["detail"]
    queued_summary = app.state.orchestrator.store.get(snapshot.task_id)
    assert publication_summary(queued_summary)["state"] == "publishing"
    assert publication_summary(queued_summary)["active"] is True


def test_platform_results_are_independent_and_failed_attempt_can_retry(tmp_path: Path, monkeypatch) -> None:
    app = create_app(_settings(tmp_path))
    snapshot, _ = _completed_content_job(app)
    monkeypatch.setattr(app.state.executor, "submit", lambda fn, **kwargs: fn(**kwargs))

    def partial_upload(*, target, **_kwargs):
        if target.platform == "douyin":
            return {"success": True, "visibility": "private"}
        raise RuntimeError("kuaishou unavailable")

    monkeypatch.setattr("content_pipeline.deferred_publishing.call_sau_target", partial_upload)
    body = {
        **_body(),
        "publish_targets": [
            {"platform": "douyin", "account": "金融破壁人"},
            {"platform": "kuaishou", "account": "破壁人"},
        ],
    }
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        first = client.post(f"/jobs/{snapshot.task_id}/publish", headers=_bearer(), json=body)
        required = first.json()["detail"]["required_confirmation"]
        client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": required},
            json=body,
        )
        after_partial = client.get(f"/status/{snapshot.task_id}", headers=_bearer()).json()

        monkeypatch.setattr(
            "content_pipeline.deferred_publishing.call_sau_target",
            lambda **_kwargs: {"success": True, "visibility": "private"},
        )
        retry_check = client.post(f"/jobs/{snapshot.task_id}/publish", headers=_bearer(), json=body)
        retry_required = retry_check.json()["detail"]["required_confirmation"]
        retry = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": retry_required},
            json=body,
        )
        after_retry = client.get(f"/status/{snapshot.task_id}", headers=_bearer()).json()

    assert after_partial["publication_attempts"][0]["status"] == "partial"
    assert after_partial["publication_attempts"][0]["results"]["kuaishou"]["success"] is False
    assert after_partial["publication_summary"]["state"] == "partial"
    assert after_partial["publication_summary"]["needs_attention"] is True
    assert retry.status_code == 202
    assert after_retry["status"] == "succeeded"
    assert after_retry["publication_attempts"][1]["status"] == "succeeded"
    assert after_retry["publication_summary"]["state"] == "published"


def test_publication_summary_distinguishes_waiting_unpublished_and_failed(tmp_path: Path, monkeypatch) -> None:
    app = create_app(_settings(tmp_path))
    store = app.state.orchestrator.store
    waiting = store.create(
        TaskInput(
            description="内容工作台 · 等待视频",
            content_type="script_video",
            topic="等待视频",
            params={"title": "等待视频", "script": "市场信息。" * 80, "dry_run": False},
            origin="content_studio",
        )
    )
    completed, _ = _completed_content_job(app)

    assert publication_summary(waiting)["state"] == "waiting_generation"
    unpublished = publication_summary(store.get(completed.task_id))
    assert unpublished["state"] == "not_published"
    assert unpublished["has_published"] is False
    assert "尚未发送到任何自媒体账号" in unpublished["message"]

    monkeypatch.setattr(
        "content_pipeline.deferred_publishing.call_sau_target",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("account session expired")),
    )
    monkeypatch.setattr(app.state.executor, "submit", lambda fn, **kwargs: fn(**kwargs))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        check = client.post(f"/jobs/{completed.task_id}/publish", headers=_bearer(), json=_body())
        required = check.json()["detail"]["required_confirmation"]
        accepted = client.post(
            f"/jobs/{completed.task_id}/publish",
            headers={**_bearer(), "X-AI-Popline-Publish-Confirmation": required},
            json=_body(),
        )
        failed_status = client.get(f"/status/{completed.task_id}", headers=_bearer()).json()
        listed = client.get("/jobs", headers=_bearer()).json()["jobs"]

    assert accepted.status_code == 202
    assert failed_status["status"] == "succeeded"
    assert failed_status["publication_summary"]["state"] == "failed"
    assert failed_status["publication_summary"]["needs_attention"] is True
    assert failed_status["publication_summary"]["targets"][0]["account"] == "金融破壁人"
    assert failed_status["publication_summary"]["targets"][0]["error"] == "account session expired"
    listed_job = next(item for item in listed if item["task_id"] == completed.task_id)
    assert listed_job["publication_summary"]["state"] == "failed"


def test_deferred_publish_session_requires_recent_login(tmp_path: Path, monkeypatch) -> None:
    app = create_app(_settings(tmp_path, web_publish_reauth_seconds=60))
    snapshot, _ = _completed_content_job(app)
    queued = []
    monkeypatch.setattr(app.state.executor, "submit", lambda fn, **kwargs: queued.append((fn, kwargs)))

    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        login = client.post("/auth/login", json={"token": ADMIN_TOKEN})
        csrf = login.json()["csrf_token"]
        check = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={"X-CSRF-Token": csrf},
            json=_body(),
        )
        required = check.json()["detail"]["required_confirmation"]
        now = time.time()
        monkeypatch.setattr(security_module.time, "time", lambda: now + 61)
        rejected = client.post(
            f"/jobs/{snapshot.task_id}/publish",
            headers={
                "X-CSRF-Token": csrf,
                "X-AI-Popline-Publish-Confirmation": required,
            },
            json=_body(),
        )

    assert rejected.status_code == 401
    assert rejected.json()["detail"] == {
        "code": "recent_authentication_required",
        "message": "recent authentication required for publishing",
    }
    assert not queued
