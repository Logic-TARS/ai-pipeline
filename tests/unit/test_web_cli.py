import importlib
import sys
import zipfile
from pathlib import Path

import pytest

from content_pipeline.settings import Settings

cli = importlib.import_module("content_pipeline.cli.main")
doctor = importlib.import_module("content_pipeline.cli.doctor")


def test_serve_rejects_wildcard_before_starting_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["ai-popline", "serve", "--host", "0.0.0.0"])
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(_env_file=None))

    with pytest.raises(SystemExit, match="wildcard listeners are not supported"):
        cli.main()


def test_serve_uses_guarded_uvicorn_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        web_bind_host="127.0.0.1",
        web_port=8765,
        web_tls_certfile=cert,
        web_tls_keyfile=key,
    )
    captured = {}

    def fake_run(app: str, **kwargs) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(sys, "argv", ["ai-popline", "serve"])
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    assert cli.main() == 0
    assert captured == {
        "app": "content_pipeline.api.app:app",
        "host": "127.0.0.1",
        "port": 8765,
        "ssl_certfile": str(cert),
        "ssl_keyfile": str(key),
        "proxy_headers": False,
        "server_header": False,
    }


def test_diagnostic_bundle_redacts_web_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        web_admin_token="admin-value-that-must-not-appear-123456",
        web_api_token="api-value-that-must-not-appear-12345678",
        web_session_secret="session-value-that-must-not-appear-1234",
    )
    bundle = tmp_path / "diagnostics.zip"
    monkeypatch.setattr(doctor, "load_settings", lambda: settings)

    assert doctor.run_doctor_bundle(bundle) == 0
    with zipfile.ZipFile(bundle) as archive:
        diagnostics = archive.read("diagnostics.txt").decode("utf-8")

    assert "admin-value-that-must-not-appear" not in diagnostics
    assert "api-value-that-must-not-appear" not in diagnostics
    assert "session-value-that-must-not-appear" not in diagnostics
    assert "web_admin_token: **********" in diagnostics


def test_serve_rejects_missing_tls_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing_cert = tmp_path / "missing.crt"
    key = tmp_path / "server.key"
    key.write_text("key", encoding="utf-8")
    settings = Settings(_env_file=None, web_tls_certfile=missing_cert, web_tls_keyfile=key)
    monkeypatch.setattr(sys, "argv", ["ai-popline", "serve"])
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    with pytest.raises(SystemExit, match="TLS certificate does not exist"):
        cli.main()
