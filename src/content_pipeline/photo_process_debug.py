from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

from content_pipeline.models import AdapterResult, ErrorCode
from content_pipeline.settings import Settings

__all__ = [
    "DEFAULT_DEBUG_URL",
    "DEFAULT_DESKTOP_HELPER_URL",
    "DebugMode",
    "SNAPSHOT_RELATIVE_PATH",
    "VISIBLE_WINDOW_TIMEOUT_SECONDS",
    "inspect_chrome_profile_processes",
    "inspect_visible_chrome_windows",
    "main",
    "open_photo_process_debug",
    "open_photo_process_desktop_debug",
]

DEFAULT_DEBUG_URL = "https://gemini.google.com/app"
DEFAULT_DESKTOP_HELPER_URL = "http://127.0.0.1:8767"
SNAPSHOT_RELATIVE_PATH = Path("logs") / "frontend_dom_snapshot.json"
VISIBLE_WINDOW_TIMEOUT_SECONDS = 12
DebugMode = Literal["automation", "desktop"]


def open_photo_process_debug(
    *,
    settings: Settings,
    url: str | None = None,
    mode: DebugMode = "automation",
    process_launcher: Any | None = None,
    process_inspector: Any | None = None,
    window_inspector: Any | None = None,
    visible_window_timeout_seconds: int = VISIBLE_WINDOW_TIMEOUT_SECONDS,
    desktop_helper_url: str = DEFAULT_DESKTOP_HELPER_URL,
) -> AdapterResult:
    """Launch Photo-Process' own foreground Gemini debug browser."""

    target_url = url or DEFAULT_DEBUG_URL
    if mode == "desktop":
        return open_photo_process_desktop_debug(
            settings=settings,
            url=target_url,
            desktop_helper_url=desktop_helper_url,
        )
    if mode != "automation":
        return _result(False, ErrorCode.INPUT_ERROR, f"unknown photo debug mode: {mode}")

    launcher = process_launcher or subprocess.Popen
    inspector = process_inspector or inspect_chrome_profile_processes
    window_checker = window_inspector or inspect_visible_chrome_windows
    script_path = settings.photo_process_dir / "启动调试浏览器.py"
    snapshot_path = settings.photo_process_dir / SNAPSHOT_RELATIVE_PATH

    evidence: dict[str, Any] = {
        "cwd": str(settings.photo_process_dir),
        "command": [str(settings.photo_process_python), str(script_path), target_url],
        "snapshot_path": str(snapshot_path),
        "purpose": "human foreground inspection only; not job completion evidence",
    }

    config_error = _validate_debug_config(settings, script_path)
    if config_error:
        return _result(False, ErrorCode.CONFIG_ERROR, config_error, evidence=evidence)

    user_data_dir = _load_photo_process_user_data_dir(settings.photo_process_dir)
    if user_data_dir:
        evidence["user_data_dir"] = str(user_data_dir)
        holders = inspector(user_data_dir)
        if holders:
            return _result(
                False,
                ErrorCode.EXTERNAL_TOOL_FAILED,
                "Photo-Process Chrome profile is already in use; close the listed process "
                "before opening foreground debug.",
                evidence={**evidence, "profile_processes": holders},
                raw={"blocked_reason": "profile_in_use"},
            )

    try:
        process = launcher(
            evidence["command"],
            cwd=settings.photo_process_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return _result(False, ErrorCode.EXTERNAL_TOOL_FAILED, str(exc), evidence=evidence)

    pid = getattr(process, "pid", None)
    window_info = _wait_for_visible_windows(window_checker, visible_window_timeout_seconds)
    gem_redirect = _detect_gem_redirect(target_url, snapshot_path)
    if gem_redirect:
        return _result(
            False,
            ErrorCode.GEM_ACCESS_FAILED,
            "Gemini did not stay on the requested Gem URL; the current profile may not have access.",
            artifacts={"snapshot_path": str(snapshot_path)},
            evidence={
                **evidence,
                "pid": pid,
                "visible_windows": window_info,
                "visible_window_detected": bool(window_info),
                **gem_redirect,
            },
            raw={"validation": "gem_redirected_to_app"},
        )
    if not window_info:
        return _result(
            False,
            ErrorCode.VALIDATION_FAILED,
            "Photo-Process debug process launched, but no visible Chrome window was detected.",
            artifacts={"snapshot_path": str(snapshot_path)},
            evidence={
                **evidence,
                "pid": pid,
                "visible_windows": [],
                "visible_window_detected": False,
                "visible_window_timeout_seconds": visible_window_timeout_seconds,
            },
            raw={"validation": "no_visible_chrome_window"},
        )
    return _result(
        True,
        ErrorCode.OK,
        None,
        artifacts={"snapshot_path": str(snapshot_path)},
        evidence={
            **evidence,
            "pid": pid,
            "visible_windows": window_info,
            "visible_window_detected": bool(window_info),
        },
    )


def open_photo_process_desktop_debug(
    *,
    settings: Settings,
    url: str,
    desktop_helper_url: str = DEFAULT_DESKTOP_HELPER_URL,
) -> AdapterResult:
    snapshot_path = settings.photo_process_dir / SNAPSHOT_RELATIVE_PATH
    user_data_dir = _load_photo_process_user_data_dir(settings.photo_process_dir)
    evidence: dict[str, Any] = {
        "mode": "desktop",
        "desktop_helper_url": desktop_helper_url,
        "url": url,
        "snapshot_path": str(snapshot_path),
        "purpose": "human foreground inspection only; not job completion evidence",
    }
    if user_data_dir is not None:
        evidence["user_data_dir"] = str(user_data_dir)

    query = {"url": url}
    if user_data_dir is not None:
        query["user_data_dir"] = str(user_data_dir)
    request_url = f"{desktop_helper_url.rstrip('/')}/open?{urlencode(query)}"
    evidence["request_url"] = request_url
    try:
        with _open_local_url(request_url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return _result(
            False,
            ErrorCode.DESKTOP_HELPER_UNAVAILABLE,
            f"desktop browser helper is unavailable: {exc}",
            evidence=evidence,
            raw={"helper_unavailable": True},
        )

    if not payload.get("ok"):
        return _result(
            False,
            ErrorCode.VALIDATION_FAILED,
            "desktop helper did not report a visible Chrome window.",
            artifacts={"snapshot_path": str(snapshot_path)},
            evidence={**evidence, "helper_result": payload},
            raw={"validation": "desktop_helper_no_visible_window"},
        )
    return _result(
        True,
        ErrorCode.OK,
        None,
        artifacts={"snapshot_path": str(snapshot_path)},
        evidence={**evidence, "helper_result": payload},
    )


def _open_local_url(url: str, timeout: int):
    opener = build_opener(ProxyHandler({}))
    return opener.open(url, timeout=timeout)


def _validate_debug_config(settings: Settings, script_path: Path) -> str | None:
    if not settings.photo_process_dir.is_dir():
        return f"Photo-Process directory not found: {settings.photo_process_dir}"
    if not settings.photo_process_python.is_file():
        return f"Photo-Process Python not found: {settings.photo_process_python}"
    if not script_path.is_file():
        return f"Photo-Process debug entrypoint not found: {script_path}"
    return None


def _load_photo_process_user_data_dir(photo_process_dir: Path) -> Path | None:
    settings_path = photo_process_dir / "settings.json"
    if not settings_path.is_file():
        return None
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = payload.get("user_data_dir")
    if not raw:
        return None
    return Path(str(raw)).expanduser()


def _detect_gem_redirect(target_url: str, snapshot_path: Path) -> dict[str, Any] | None:
    parsed_target = target_url.rstrip("/")
    if "/gem/" not in parsed_target:
        return None
    snapshot = _read_snapshot_meta(snapshot_path)
    final_url = str(snapshot.get("url", "")).rstrip("/")
    if not final_url:
        return None
    if final_url == parsed_target:
        return None
    if final_url == "https://gemini.google.com/app" or "/app" in final_url:
        return {
            "requested_url": target_url,
            "final_url": snapshot.get("url"),
            "snapshot_title": snapshot.get("title"),
            "gem_redirected_to_app": True,
        }
    return None


def _read_snapshot_meta(snapshot_path: Path) -> dict[str, Any]:
    if not snapshot_path.is_file():
        return {}
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        "url": payload.get("url"),
        "title": payload.get("title"),
    }


def inspect_chrome_profile_processes(user_data_dir: Path) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    profile = str(user_data_dir).lower()
    profile_literal = profile.replace("'", "''")
    script = (
        f"$profile = '{profile_literal}'; "
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process -Filter \"name = 'chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($profile) } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    return [
        {"pid": row.get("ProcessId"), "command_line": row.get("CommandLine", "")}
        for row in rows
        if isinstance(row, dict)
    ]


def inspect_visible_chrome_windows() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-Process -Name chrome | "
        "Where-Object { $_.MainWindowHandle -ne 0 } | "
        "Select-Object Id,MainWindowTitle,MainWindowHandle | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    return [
        {
            "pid": row.get("Id"),
            "title": row.get("MainWindowTitle", ""),
            "window_handle": row.get("MainWindowHandle"),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _wait_for_visible_windows(window_checker: Any, timeout_seconds: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        windows = window_checker()
        if windows:
            return windows
        if time.monotonic() >= deadline:
            return []
        time.sleep(1)


def _result(
    ok: bool,
    code: ErrorCode,
    message: str | None,
    *,
    artifacts: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    raw: dict[str, Any] | None = None,
) -> AdapterResult:
    return AdapterResult(
        ok=ok,
        tool="Photo-Process foreground debug",
        code=code,
        message=message,
        artifacts=artifacts or {},
        evidence=evidence or {},
        raw=raw or {},
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="AI Pipeline diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)
    photo_debug = subparsers.add_parser("photo-debug", help="Open Photo-Process foreground debug browser")
    photo_debug.add_argument("--url", default=DEFAULT_DEBUG_URL, help="Gemini or Gem URL to open")
    photo_debug.add_argument("--mode", choices=["automation", "desktop"], default="automation")
    photo_debug.add_argument("--desktop-helper-url", default=DEFAULT_DESKTOP_HELPER_URL)
    desktop_helper = subparsers.add_parser("desktop-helper", help="Run the local desktop browser helper")
    desktop_helper.add_argument("--host", default="127.0.0.1")
    desktop_helper.add_argument("--port", type=int, default=8767)

    args = parser.parse_args(argv)
    if args.command == "photo-debug":
        from content_pipeline.settings import load_settings

        result = open_photo_process_debug(
            settings=load_settings(),
            url=args.url,
            mode=args.mode,
            desktop_helper_url=args.desktop_helper_url,
        )
        print(result.model_dump_json(indent=2))
        return 0 if result.ok else 1
    if args.command == "desktop-helper":
        from content_pipeline.desktop_browser_helper import main as helper_main

        return helper_main(["--host", args.host, "--port", str(args.port)])
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
