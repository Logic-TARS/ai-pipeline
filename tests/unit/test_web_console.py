import json
from importlib.resources import files
from pathlib import Path

from fastapi.testclient import TestClient

from content_pipeline.api.app import create_app, task_fingerprint
from content_pipeline.models import JobStatus, PipelineStep, TaskInput
from content_pipeline.settings import Settings

ADMIN_TOKEN = "admin-" + "a" * 32
API_TOKEN = "api-" + "b" * 32
SESSION_SECRET = "session-" + "c" * 32


def _settings(tmp_path: Path, **overrides) -> Settings:
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    values = {
        "data_dir": tmp_path / "sensitive-output-path",
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


def _client(tmp_path: Path, **overrides) -> TestClient:
    return TestClient(
        create_app(_settings(tmp_path, **overrides)),
        base_url="http://testserver",
        client=("127.0.0.1", 50000),
    )


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def test_console_shell_and_static_assets_are_public_but_data_is_protected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        page = client.get("/")
        css = client.get("/static/styles.css")
        javascript = client.get("/static/app.js")
        content_javascript = client.get("/static/content-studio.js")
        bootstrap = client.get("/ui/bootstrap")

    assert page.status_code == 200
    assert "AI Popline · 内容控制台" in page.text
    assert 'id="login-view"' in page.text
    assert 'id="app-shell"' in page.text
    assert 'id="template-cards"' in page.text
    assert "选择内容类型" in page.text
    assert "让内容从灵感到成片" in page.text
    assert 'class="hero-orbit"' in page.text
    assert 'class="stat-icon"' in page.text
    assert "生成金融口播稿" not in page.text
    assert '<script src="/static/app.js" defer></script>' in page.text
    assert page.text.count('class="button ghost compact theme-toggle"') == 1
    assert 'class="icon-button theme-toggle auth-theme-toggle"' in page.text
    assert 'id="content-voice-rate"' in page.text
    assert "朗读速度" in page.text
    assert css.status_code == 200
    assert "--surface" in css.text
    assert "--brand-gradient" in css.text
    assert "--workspace-panel-height" in css.text
    assert "height: var(--workspace-panel-height)" in css.text
    assert ".field-label { display: inline-flex; align-items: baseline; gap: 0.2rem; }" in css.text
    assert (
        ".jobs-panel, .detail-panel, .draft-library, .studio-editor-panel { height: auto; max-height: none; }"
        in css.text
    )
    assert "#studio-editor:not([hidden])" in css.text
    assert "studio-action-controls" in css.text
    assert 'html[data-theme="light"]' in css.text
    assert "@media (prefers-contrast: more)" in css.text
    assert "@media (prefers-reduced-motion: reduce)" in css.text
    assert javascript.status_code == 200
    assert '<span class="field-label">${escapeHtml(field.label)}${requiredLabel}</span>' in javascript.text
    assert '<span class="field-label">视频标题<span class="required">*</span></span>' in page.text
    assert "localStorage.setItem(THEME_STORAGE_KEY, resolved)" in javascript.text
    assert 'FORM_MEMORY_STORAGE_KEY = "ai-popline-form-memory-v1"' in javascript.text
    assert "function rememberCurrentTaskForm()" in javascript.text
    assert "rememberedField(taskParamScope(contentType), field.name)" in javascript.text
    assert "publish_settings" in javascript.text
    assert 'response.status === 401 && errorCode === "authentication_required"' in javascript.text
    assert 'payload.detail?.code === "recent_authentication_required"' in javascript.text
    assert "发布前需要重新验证管理员令牌" in javascript.text
    assert 'apiRequest("/ui/bootstrap")' in javascript.text
    assert content_javascript.status_code == 200
    assert 'studio.request("/content/bootstrap")' in content_javascript.text
    assert "function renderTemplateCards()" in content_javascript.text
    assert "function templateIcon(templateId)" in content_javascript.text
    assert "data-template-id" in content_javascript.text
    assert "创建 AI 简报口播初稿" in content_javascript.text
    assert "studio.request(`/content/drafts/${draft.draft_id}/video`" in content_javascript.text
    assert 'STUDIO_FORM_MEMORY_STORAGE_KEY = "ai-popline-studio-form-memory-v1"' in content_javascript.text
    assert "function rememberedVoiceRate()" in content_javascript.text
    assert "function parseVoiceRate()" in content_javascript.text
    assert "rememberVoiceRate(voiceRate)" in content_javascript.text
    assert "voice_rate: voiceRate" in content_javascript.text
    assert "正在拉取资料并生成视频" in content_javascript.text
    assert 'studio.request(`/content/drafts/${draftId}`, { method: "DELETE" })' in content_javascript.text
    assert (
        'studio.request("/content/drafts/batch-delete", { method: "POST", body: { draft_ids: draftIds } })'
        in content_javascript.text
    )
    assert "studio-publish-toggle" not in page.text
    assert "handleStudioPublishToggle" not in content_javascript.text
    assert 'id="job-publish-dialog"' in page.text
    assert 'id="delete-selected-drafts"' in page.text
    assert 'id="delete-selected-jobs"' in page.text
    assert 'apiRequest("/jobs?limit=100")' in javascript.text
    assert 'apiRequest(`/jobs/${taskId}`, { method: "DELETE" })' in javascript.text
    assert 'apiRequest("/jobs/batch-delete", { method: "POST", body: { task_ids: taskIds } })' in javascript.text
    assert 'apiRequest(`/jobs/${taskId}`, { method: "PATCH", body: { display_name: displayName } })' in javascript.text
    assert 'id="rename-job-dialog"' in page.text
    assert "apiRequest(`/jobs/${taskId}/events?limit=100`)" in javascript.text
    assert "apiRequest(`/jobs/${taskId}/artifacts`)" in javascript.text
    assert "apiRequest(`/jobs/${taskId}/publish-readiness`)" in javascript.text
    assert "submitDeferredPublication" in javascript.text
    assert "function publicationStatusBadge(summary)" in javascript.text
    assert "function renderPublicationOverview(summary)" in javascript.text
    assert 'class="publication-summary-card state-${escapeHtml(summary.state)}"' in javascript.text
    assert "<th>生成状态</th><th>发布状态</th>" in page.text
    assert '<progress class="progress-bar" role="progressbar"' in javascript.text
    assert "function renderJobProgress(snapshot, contentType)" in javascript.text
    assert "function renderValidationSummary(validation)" in javascript.text
    assert "function compactEvents(events)" in javascript.text
    assert 'elements["publish-confirm-input"].value.trim() !== "确认发布"' in javascript.text
    assert 'elements["job-publish-confirm-input"].value.trim() !== "确认发布"' in javascript.text
    assert bootstrap.status_code == 401
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_packaged_web_assets_are_available() -> None:
    static = files("content_pipeline.web").joinpath("static")

    assert static.joinpath("index.html").is_file()
    assert static.joinpath("styles.css").is_file()
    assert static.joinpath("app.js").is_file()
    assert static.joinpath("content-studio.js").is_file()


def test_job_status_returns_persisted_safe_progress(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    task_id = app.state.orchestrator.submit(
        TaskInput(
            description="口播进度",
            content_type="script_video",
            params={"title": "资讯", "script": "市场信息。" * 80},
        )
    )
    app.state.orchestrator.store.set_progress(
        task_id,
        percent=45,
        phase="获取视频素材",
        message="MoneyPrinterTurbo 正在获取视频素材",
        is_estimate=True,
    )
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        response = client.get(f"/status/{task_id}", headers=_bearer())
        events = client.get(f"/jobs/{task_id}/events", headers=_bearer())

    assert response.status_code == 200
    assert response.json()["progress"] == {
        "percent": 45,
        "phase": "获取视频素材",
        "message": "MoneyPrinterTurbo 正在获取视频素材",
        "updated_at": response.json()["progress"]["updated_at"],
        "is_estimate": True,
    }
    progress_events = [event for event in events.json()["events"] if event["event"] == "progress_updated"]
    assert progress_events[-1]["payload"]["percent"] == 45


def test_ui_bootstrap_describes_supported_pipelines_without_sensitive_settings(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/ui/bootstrap", headers=_bearer())

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_contract_version"] == 2
    assert payload["features"] == {
        "content_draft_crud": True,
        "content_draft_bulk_delete": True,
        "job_rename": True,
        "job_delete": True,
        "job_bulk_delete": True,
    }
    pipelines = {pipeline["content_type"]: pipeline for pipeline in payload["pipelines"]}
    assert set(pipelines) == {
        "anime",
        "finance",
        "ai_briefing",
        "ai_art",
        "xhs_image_note",
        "grouped_anime",
        "japanese",
        "script_video",
    }
    assert {field["name"] for field in pipelines["script_video"]["fields"]} >= {
        "title",
        "script",
        "dry_run",
        "voice_rate",
    }
    assert {field["name"] for field in pipelines["ai_briefing"]["fields"]} >= {"date", "dry_run", "voice_rate"}
    voice_rate_field = next(field for field in pipelines["script_video"]["fields"] if field["name"] == "voice_rate")
    assert voice_rate_field["minimum"] == 0.55
    assert voice_rate_field["maximum"] == 1.2
    assert {field["name"] for field in pipelines["ai_art"]["fields"]} >= {
        "source_dir",
        "image_prompt",
        "title",
        "group_size",
    }
    xhs_fields = {field["name"]: field for field in pipelines["xhs_image_note"]["fields"]}
    assert set(xhs_fields) >= {"source_dir", "image_prompt", "title", "note", "tags", "dry_run"}
    assert xhs_fields["image_prompt"]["required"] is True
    assert "3:4" in xhs_fields["image_prompt"]["placeholder"]
    assert payload["auth_required"] is True
    assert payload["publish_enabled"] is False
    serialized = response.text
    assert ADMIN_TOKEN not in serialized
    assert API_TOKEN not in serialized
    assert SESSION_SECRET not in serialized
    assert "sensitive-output-path" not in serialized


def test_ui_bootstrap_applies_enabled_ai_art_pipeline_defaults(tmp_path: Path) -> None:
    defaults = tmp_path / "pipeline.defaults.yaml"
    defaults.write_text(
        """
enabled: true
pipelines:
  ai_art:
    params:
      source_dir: G:/Job/Photo-Datasets/input
      archive_dir: G:/Job/Photo-Datasets/done
      failed_dir: G:/Job/Photo-Datasets/failed
      image_prompt: 请保持主体一致，增强画面质感。
      title: AI绘画作品集
      description: AI图像处理作品集
      tags: [AI绘画, 作品集]
      group_size: 4
  xhs_image_note:
    params:
      source_dir: G:/Job/Photo-Datasets/input
      archive_dir: G:/Job/Photo-Datasets/done
      failed_dir: G:/Job/Photo-Datasets/failed
      image_prompt: 请将图片处理为适合小红书图文的 3:4 竖图。
      title: 小红书图文标题
      note: 小红书正文
      tags: [AI绘画, 小红书图文]
      dry_run: true
""",
        encoding="utf-8",
    )

    with _client(tmp_path, pipeline_defaults_file=defaults) as client:
        response = client.get("/ui/bootstrap", headers=_bearer())

    assert response.status_code == 200
    pipelines = {pipeline["content_type"]: pipeline for pipeline in response.json()["pipelines"]}
    ai_art_fields = {field["name"]: field for field in pipelines["ai_art"]["fields"]}
    assert ai_art_fields["source_dir"]["default"] == "G:/Job/Photo-Datasets/input"
    assert ai_art_fields["archive_dir"]["default"] == "G:/Job/Photo-Datasets/done"
    assert ai_art_fields["failed_dir"]["default"] == "G:/Job/Photo-Datasets/failed"
    assert ai_art_fields["image_prompt"]["default"] == "请保持主体一致，增强画面质感。"
    assert ai_art_fields["title"]["default"] == "AI绘画作品集"
    assert ai_art_fields["description"]["default"] == "AI图像处理作品集"
    assert ai_art_fields["tags"]["default"] == ["AI绘画", "作品集"]
    assert ai_art_fields["group_size"]["default"] == 4
    assert ai_art_fields["image_prompt"]["required"] is True
    xhs_fields = {field["name"]: field for field in pipelines["xhs_image_note"]["fields"]}
    assert xhs_fields["source_dir"]["default"] == "G:/Job/Photo-Datasets/input"
    assert xhs_fields["archive_dir"]["default"] == "G:/Job/Photo-Datasets/done"
    assert xhs_fields["failed_dir"]["default"] == "G:/Job/Photo-Datasets/failed"
    assert xhs_fields["image_prompt"]["default"] == "请将图片处理为适合小红书图文的 3:4 竖图。"
    assert xhs_fields["title"]["default"] == "小红书图文标题"
    assert xhs_fields["note"]["default"] == "小红书正文"
    assert xhs_fields["tags"]["default"] == ["AI绘画", "小红书图文"]
    assert xhs_fields["dry_run"]["default"] is True
    assert xhs_fields["image_prompt"]["required"] is True


def test_console_session_can_preflight_with_csrf(tmp_path: Path) -> None:
    task = {
        "description": "会话预检",
        "content_type": "anime",
        "publish": False,
        "params": {"script": "第一幕：会话安全测试。", "dry_run": True},
    }
    with _client(tmp_path) as client:
        login = client.post("/auth/login", json={"token": ADMIN_TOKEN})
        csrf = login.json()["csrf_token"]
        response = client.post("/validate-task", headers={"X-CSRF-Token": csrf}, json=task)

    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_job_delete_api_removes_terminal_jobs_and_blocks_running_jobs(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    terminal = app.state.orchestrator.submit(TaskInput(description="可删除任务"))
    second = app.state.orchestrator.submit(TaskInput(description="批量删除任务"))
    running = app.state.orchestrator.submit(TaskInput(description="运行中任务"))
    app.state.orchestrator.store.finish(terminal, JobStatus.SUCCEEDED)
    app.state.orchestrator.store.finish(second, JobStatus.FAILED, "failed for test")
    app.state.orchestrator.store.mark_running(running, PipelineStep.ROUTE)

    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        renamed = client.patch(f"/jobs/{second}", headers=_bearer(), json={"display_name": "新的显示名称"})
        read_back = client.get(f"/jobs/{second}", headers=_bearer())
        deleted = client.delete(f"/jobs/{terminal}", headers=_bearer())
        missing = client.get(f"/status/{terminal}", headers=_bearer())
        blocked = client.delete(f"/jobs/{running}", headers=_bearer())
        batch = client.post("/jobs/batch-delete", headers=_bearer(), json={"task_ids": [second, running, terminal]})
        listed = client.get("/jobs", headers=_bearer()).json()["jobs"]

    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "新的显示名称"
    assert renamed.json()["task"]["description"] == "批量删除任务"
    assert read_back.json()["display_name"] == "新的显示名称"
    assert deleted.status_code == 200
    assert deleted.json() == {"task_id": terminal, "deleted": True}
    assert missing.status_code == 404
    assert blocked.status_code == 409
    assert batch.status_code == 200
    assert batch.json()["deleted"] == [second]
    assert batch.json()["blocked"] == [running]
    assert batch.json()["not_found"] == [terminal]
    assert {job["task_id"] for job in listed} == {running}


def test_task_preflight_normalizes_params_and_returns_bound_fingerprint(tmp_path: Path) -> None:
    task = TaskInput(
        description="动漫控制台干运行",
        content_type="anime",
        topic="测试主题",
        params={"script": "第一幕：安全测试。", "dry_run": True},
    )
    with _client(tmp_path) as client:
        response = client.post("/validate-task", headers=_bearer(), json=task.model_dump(mode="json"))
        jobs = client.get("/jobs", headers=_bearer())

    assert response.status_code == 200
    assert jobs.json() == {"jobs": []}
    payload = response.json()
    normalized = TaskInput.model_validate(payload["task"])
    assert payload["valid"] is True
    assert normalized.params["dry_run"] is True
    assert payload["task_fingerprint"] == task_fingerprint(normalized)
    assert any("安全干运行" in warning for warning in payload["warnings"])


def test_request_validation_does_not_echo_task_body(tmp_path: Path) -> None:
    task = {
        "content_type": "ai_art",
        "params": {"source_dir": "G:/do-not-echo/private-source"},
    }
    with _client(tmp_path) as client:
        response = client.post("/validate-task", headers=_bearer(), json=task)

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == "description"
    assert "do-not-echo" not in response.text


def test_task_preflight_returns_sanitized_field_errors(tmp_path: Path) -> None:
    task = {
        "description": "缺少 AI Art 必填字段",
        "content_type": "ai_art",
        "publish": False,
        "params": {"source_dir": "G:/private/source"},
    }
    with _client(tmp_path) as client:
        response = client.post("/validate-task", headers=_bearer(), json=task)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "task_validation_failed"
    assert {error["field"] for error in detail["errors"]} == {"image_prompt", "title"}
    assert "G:/private/source" not in response.text
    assert all(set(error) == {"field", "message", "type"} for error in detail["errors"])


def test_task_preflight_blocks_web_publish_when_server_guard_is_off(tmp_path: Path) -> None:
    task = {
        "description": "不允许的发布任务",
        "content_type": "anime",
        "publish": True,
        "params": {"script": "安全测试", "dry_run": True},
    }
    with _client(tmp_path) as client:
        response = client.post("/validate-task", headers=_bearer(), json=task)

    assert response.status_code == 403
    assert response.json()["detail"] == "web publishing is disabled"


def test_task_preflight_rejects_platform_not_supported_by_pipeline(tmp_path: Path) -> None:
    task = {
        "description": "平台不匹配",
        "content_type": "japanese",
        "publish": False,
        "publish_targets": [{"platform": "douyin", "account": "test"}],
        "params": {"source_dir": "G:/images", "dry_run": True},
    }
    with _client(tmp_path) as client:
        response = client.post("/validate-task", headers=_bearer(), json=task)

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert errors == [{"field": "task", "message": "流水线不支持以下发布平台：douyin"}]


def _ready_briefing_draft(tmp_path: Path) -> str:
    """Write a valid ready ai_briefing draft directly to disk; return its draft_id."""
    from content_pipeline.content_studio.models import ContentDraft, ResearchSource
    from content_pipeline.content_studio.store import ContentDraftStore

    draft_id = "b" * 32
    draft = ContentDraft(
        draft_id=draft_id,
        template_id="ai_briefing_90s",
        title="每日 AI 简报测试",
        script="未来一周科技与金融领域迎来多项关键进展。" * 20,
        status="ready",
        revision=1,
        research=[
            ResearchSource(
                source_id="ai-briefing",
                label="AI 简报",
                skill_id="AI_BRIEFING_MARKDOWN",
                status="succeeded",
                summary="最新 AI 简报",
            )
        ],
    )
    ContentDraftStore(tmp_path / "sensitive-output-path")._save_unlocked(draft)
    return draft_id


def test_content_studio_video_defaults_to_local_only(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.orchestrator.run = lambda _task_id: None
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        draft_id = _ready_briefing_draft(tmp_path)
        response = client.post(
            f"/content/drafts/{draft_id}/video",
            headers=_bearer(),
            json={"revision": 1, "dry_run": False, "voice_rate": 0.9},
        )
        task_id = response.json()["task_id"]
        status = client.get(f"/status/{task_id}", headers=_bearer())
        listed = client.get("/jobs", headers=_bearer())

    assert response.status_code == 202
    assert status.json()["publication_summary"]["state"] == "waiting_generation"
    listed_job = next(item for item in listed.json()["jobs"] if item["task_id"] == task_id)
    assert listed_job["publication_summary"]["label"] == "待生成"
    snapshot = json.loads(
        (tmp_path / "sensitive-output-path" / "jobs" / task_id / "status.json").read_text(encoding="utf-8")
    )
    assert snapshot["task"]["publish"] is False
    assert snapshot["task"]["publish_targets"] == []
    assert snapshot["task"]["params"]["voice_rate"] == 0.9


def test_content_studio_never_publishes_during_generation_and_records_provenance(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, web_publish_enabled=True))
    app.state.orchestrator.run = lambda _task_id: None
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        draft_id = _ready_briefing_draft(tmp_path)
        response = client.post(
            f"/content/drafts/{draft_id}/video",
            headers=_bearer(),
            json={
                "revision": 1,
                "dry_run": False,
                "publish": True,
                "publish_targets": [{"platform": "douyin", "account": "金融破壁人"}],
            },
        )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    snapshot = json.loads(
        (tmp_path / "sensitive-output-path" / "jobs" / task_id / "status.json").read_text(encoding="utf-8")
    )
    assert snapshot["task"]["publish"] is False
    assert snapshot["task"]["publish_targets"] == []
    assert snapshot["task"]["origin"] == "content_studio"
    assert snapshot["task"]["source_draft_id"] == draft_id
    assert snapshot["task"]["source_draft_revision"] == 1


def test_crud_route_contract_registers_expected_methods(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    paths = app.openapi()["paths"]

    assert set(paths["/content/drafts"]) >= {"get", "post"}
    assert set(paths["/content/drafts/batch-delete"]) == {"post"}
    assert set(paths["/content/drafts/{draft_id}"]) >= {"get", "patch", "delete"}
    assert set(paths["/jobs"]) == {"get"}
    assert set(paths["/jobs/batch-delete"]) == {"post"}
    assert set(paths["/jobs/{task_id}"]) >= {"get", "patch", "delete"}

    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        draft_alias = client.post("/content/drafts/delete", headers=_bearer(), json={"draft_ids": ["0" * 32]})
        job_alias = client.post("/jobs/delete", headers=_bearer(), json={"task_ids": ["0" * 32]})

    assert draft_alias.status_code == 200
    assert job_alias.status_code == 200
