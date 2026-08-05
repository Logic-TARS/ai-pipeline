from importlib.resources import files
from pathlib import Path

from fastapi.testclient import TestClient

from content_pipeline.api.app import create_app, task_fingerprint
from content_pipeline.models import TaskInput
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
    return Settings(**values)


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
    assert "生成金融口播稿" not in page.text
    assert '<script src="/static/app.js" defer></script>' in page.text
    assert page.text.count('class="button ghost compact theme-toggle"') == 1
    assert 'class="icon-button theme-toggle auth-theme-toggle"' in page.text
    assert css.status_code == 200
    assert "--surface" in css.text
    assert 'html[data-theme="light"]' in css.text
    assert javascript.status_code == 200
    assert "localStorage.setItem(THEME_STORAGE_KEY, resolved)" in javascript.text
    assert 'apiRequest("/ui/bootstrap")' in javascript.text
    assert content_javascript.status_code == 200
    assert 'studio.request("/content/bootstrap")' in content_javascript.text
    assert "function renderTemplateCards()" in content_javascript.text
    assert "data-template-id" in content_javascript.text
    assert "创建 AI 简报口播初稿" in content_javascript.text
    assert "studio.request(`/content/drafts/${draft.draft_id}/video`" in content_javascript.text
    assert 'apiRequest("/jobs?limit=100")' in javascript.text
    assert "apiRequest(`/jobs/${taskId}/events?limit=100`)" in javascript.text
    assert "apiRequest(`/jobs/${taskId}/artifacts`)" in javascript.text
    assert 'elements["publish-confirm-input"].value.trim() !== "确认发布"' in javascript.text
    assert bootstrap.status_code == 401
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_packaged_web_assets_are_available() -> None:
    static = files("content_pipeline.web").joinpath("static")

    assert static.joinpath("index.html").is_file()
    assert static.joinpath("styles.css").is_file()
    assert static.joinpath("app.js").is_file()
    assert static.joinpath("content-studio.js").is_file()


def test_ui_bootstrap_describes_supported_pipelines_without_sensitive_settings(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/ui/bootstrap", headers=_bearer())

    assert response.status_code == 200
    payload = response.json()
    pipelines = {pipeline["content_type"]: pipeline for pipeline in payload["pipelines"]}
    assert set(pipelines) == {
        "anime",
        "finance",
        "ai_briefing",
        "ai_art",
        "grouped_anime",
        "japanese",
        "script_video",
    }
    assert {field["name"] for field in pipelines["script_video"]["fields"]} >= {"title", "script", "dry_run"}
    assert {field["name"] for field in pipelines["ai_art"]["fields"]} >= {
        "source_dir",
        "image_prompt",
        "title",
        "group_size",
    }
    assert payload["auth_required"] is True
    assert payload["publish_enabled"] is False
    serialized = response.text
    assert ADMIN_TOKEN not in serialized
    assert API_TOKEN not in serialized
    assert SESSION_SECRET not in serialized
    assert "sensitive-output-path" not in serialized


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
