from __future__ import annotations

from pathlib import Path

import pytest

from content_pipeline.models import ErrorCode
from content_pipeline.photo_process_debug import open_photo_process_debug
from content_pipeline.settings import Settings


class FakeProcess:
    pid = 12345


class FakeLauncher:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return FakeProcess()


def _make_photo_process(tmp_path: Path) -> tuple[Settings, Path]:
    photo_dir = tmp_path / "Photo-Process"
    photo_dir.mkdir()
    python_exe = tmp_path / "python.exe"
    python_exe.write_text("", encoding="utf-8")
    debug_script = photo_dir / "启动调试浏览器.py"
    debug_script.write_text("print('debug')\n", encoding="utf-8")
    (photo_dir / "settings.json").write_text(
        '{"user_data_dir": "C:\\\\Users\\\\Family\\\\.wjz_browser_data"}',
        encoding="utf-8",
    )
    settings = Settings(photo_process_dir=photo_dir, photo_process_python=python_exe)
    return settings, debug_script


def test_open_photo_process_debug_reports_config_error(tmp_path: Path) -> None:
    settings = Settings(
        photo_process_dir=tmp_path / "missing-photo-process",
        photo_process_python=tmp_path / "missing-python.exe",
    )

    result = open_photo_process_debug(settings=settings)

    assert result.ok is False
    assert result.code == ErrorCode.CONFIG_ERROR
    assert "Photo-Process directory not found" in str(result.message)


def test_open_photo_process_debug_blocks_when_profile_in_use(tmp_path: Path) -> None:
    settings, _ = _make_photo_process(tmp_path)
    launcher = FakeLauncher()

    result = open_photo_process_debug(
        settings=settings,
        url="https://gemini.google.com/gem/test",
        process_launcher=launcher,
        process_inspector=lambda _profile: [{"pid": 999, "command_line": "chrome --user-data-dir=..."}],
    )

    assert result.ok is False
    assert result.code == ErrorCode.EXTERNAL_TOOL_FAILED
    assert result.raw["blocked_reason"] == "profile_in_use"
    assert result.evidence["profile_processes"][0]["pid"] == 999
    assert launcher.calls == []


def test_open_photo_process_debug_uses_photo_process_entrypoint(tmp_path: Path) -> None:
    settings, debug_script = _make_photo_process(tmp_path)
    launcher = FakeLauncher()

    result = open_photo_process_debug(
        settings=settings,
        url="https://gemini.google.com/gem/test",
        process_launcher=launcher,
        process_inspector=lambda _profile: [],
        window_inspector=lambda: [{"pid": 12345, "title": "Gemini", "window_handle": 111}],
    )

    assert result.ok is True
    assert result.code == ErrorCode.OK
    assert result.evidence["pid"] == 12345
    assert result.evidence["visible_window_detected"] is True
    command, kwargs = launcher.calls[0]
    assert command == [
        str(settings.photo_process_python),
        str(debug_script),
        "https://gemini.google.com/gem/test",
    ]
    assert "chrome.exe" not in " ".join(command).lower()
    assert kwargs["cwd"] == settings.photo_process_dir
    assert result.artifacts["snapshot_path"].endswith("frontend_dom_snapshot.json")


def test_open_photo_process_debug_fails_when_no_visible_window(tmp_path: Path) -> None:
    settings, _ = _make_photo_process(tmp_path)
    launcher = FakeLauncher()

    result = open_photo_process_debug(
        settings=settings,
        url="https://gemini.google.com/app",
        process_launcher=launcher,
        process_inspector=lambda _profile: [],
        window_inspector=lambda: [],
        visible_window_timeout_seconds=0,
    )

    assert result.ok is False
    assert result.code == ErrorCode.VALIDATION_FAILED
    assert result.raw["validation"] == "no_visible_chrome_window"
    assert launcher.calls


def test_open_photo_process_debug_reports_gem_redirect(tmp_path: Path) -> None:
    settings, _ = _make_photo_process(tmp_path)
    launcher = FakeLauncher()
    snapshot = settings.photo_process_dir / "logs" / "frontend_dom_snapshot.json"
    snapshot.parent.mkdir()
    snapshot.write_text(
        '{"url": "https://gemini.google.com/app", "title": "Google Gemini"}',
        encoding="utf-8",
    )

    result = open_photo_process_debug(
        settings=settings,
        url="https://gemini.google.com/gem/ee8884bad495",
        process_launcher=launcher,
        process_inspector=lambda _profile: [],
        window_inspector=lambda: [],
        visible_window_timeout_seconds=0,
    )

    assert result.ok is False
    assert result.code == ErrorCode.GEM_ACCESS_FAILED
    assert result.raw["validation"] == "gem_redirected_to_app"
    assert result.evidence["final_url"] == "https://gemini.google.com/app"


def test_open_photo_process_debug_desktop_helper_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, _ = _make_photo_process(tmp_path)

    def raise_connection_error(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("content_pipeline.photo_process_debug._open_local_url", raise_connection_error)

    result = open_photo_process_debug(
        settings=settings,
        url="https://gemini.google.com/app",
        mode="desktop",
        desktop_helper_url="http://127.0.0.1:8767",
    )

    assert result.ok is False
    assert result.code == ErrorCode.DESKTOP_HELPER_UNAVAILABLE
    assert result.raw["helper_unavailable"] is True


def test_open_photo_process_debug_desktop_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, _ = _make_photo_process(tmp_path)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true, "pid": 321, "visible_window_detected": true}'

    monkeypatch.setattr("content_pipeline.photo_process_debug._open_local_url", lambda *args, **kwargs: FakeResponse())

    result = open_photo_process_debug(
        settings=settings,
        url="https://gemini.google.com/app",
        mode="desktop",
        desktop_helper_url="http://127.0.0.1:8767",
    )

    assert result.ok is True
    assert result.code == ErrorCode.OK
    assert result.evidence["helper_result"]["pid"] == 321
