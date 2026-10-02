from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_pipeline.account_status import collect_account_status
from content_pipeline.api.app import create_app
from content_pipeline.errors import ConfigError
from content_pipeline.models import RouteResult
from content_pipeline.pipeline_config import (
    apply_pipeline_defaults,
    load_effective_pipeline_defaults,
    save_pipeline_defaults_override,
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
        "web_publish_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def test_pipeline_defaults_override_enables_params_merge(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    before = load_effective_pipeline_defaults(settings)
    assert before.get("enabled") is False

    save_pipeline_defaults_override(
        settings,
        {"enabled": True, "pipelines": {"finance": {"params": {"script_writer": "rule", "date": "auto"}}}},
    )
    effective = load_effective_pipeline_defaults(settings)
    assert effective["enabled"] is True
    assert effective["pipelines"]["finance"]["params"]["script_writer"] == "rule"

    route = apply_pipeline_defaults(
        RouteResult(content_type="finance", topic="基金日报", params={"date": "20260904"}),
        settings=settings,
        task_id="a" * 32,
    )
    # explicit task params win; defaults fill the rest
    assert route.params == {"date": "20260904", "script_writer": "rule"}


def test_pipeline_defaults_override_disabled_by_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    route = RouteResult(content_type="finance", topic="基金日报", params={})
    assert apply_pipeline_defaults(route, settings=settings, task_id="a" * 32).params == {}


def test_pipeline_defaults_override_validation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ConfigError):
        save_pipeline_defaults_override(
            settings,
            {"enabled": True, "pipelines": {"finance": {"params": ["not-a-dict"]}}},
        )


def test_pipeline_defaults_api_roundtrip(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        initial = client.get("/pipeline-defaults", headers=_bearer())
        unknown = client.put(
            "/pipeline-defaults",
            headers=_bearer(),
            json={"enabled": True, "pipelines": {"not_a_pipeline": {"params": {}}}},
        )
        updated = client.put(
            "/pipeline-defaults",
            headers=_bearer(),
            json={"enabled": True, "pipelines": {"finance": {"params": {"script_writer": "rule"}}}},
        )
        reread = client.get("/pipeline-defaults", headers=_bearer())

    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert unknown.status_code == 422
    assert updated.status_code == 200
    assert reread.json()["enabled"] is True
    assert reread.json()["pipelines"]["finance"]["params"] == {"script_writer": "rule"}


def test_account_status_cookie_fallback(tmp_path: Path) -> None:
    sau_dir = tmp_path / "sau"
    cookies = sau_dir / "cookies"
    cookies.mkdir(parents=True)
    (cookies / "douyin_金融破壁人.json").write_text("{}", encoding="utf-8")
    (cookies / "tencent_破壁人WallBreaker.json").write_text("{}", encoding="utf-8")
    (cookies / "notes.txt").write_text("ignore", encoding="utf-8")
    settings = _settings(tmp_path, sau_dir=sau_dir, sau_bridge_url="")

    status = collect_account_status(settings)

    assert status["source"] == "cookies"
    by_key = {(item["platform"], item["account"]): item for item in status["accounts"]}
    assert by_key[("douyin", "金融破壁人")]["has_cookie"] is True
    assert by_key[("douyin", "金融破壁人")]["cookie_modified"]
    assert by_key[("tencent", "破壁人WallBreaker")]["has_cookie"] is True
    assert len(by_key) == 2


def test_account_status_api(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, sau_bridge_url="", sau_dir=tmp_path / "empty-sau"))
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        response = client.get("/account-status", headers=_bearer())

    assert response.status_code == 200
    assert response.json()["source"] == "cookies"
    assert response.json()["accounts"] == []
