from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from content_pipeline.photo_process_debug import inspect_visible_chrome_windows


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767
DEFAULT_CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> Path | None:
    for path in DEFAULT_CHROME_PATHS:
        if path.is_file():
            return path
    return None


def open_visible_chrome(
    *,
    url: str,
    user_data_dir: Path | None = None,
    chrome_path: Path | None = None,
    window_timeout_seconds: int = 12,
) -> dict[str, Any]:
    chrome = chrome_path or find_chrome()
    if chrome is None:
        return {"ok": False, "error": "chrome_not_found"}

    command = [str(chrome), "--new-window", "--start-maximized"]
    if user_data_dir is not None:
        command.append(f"--user-data-dir={user_data_dir}")
    command.append(url)

    before_handles = {item.get("window_handle") for item in inspect_visible_chrome_windows()}
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + window_timeout_seconds
    windows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        current = inspect_visible_chrome_windows()
        windows = [item for item in current if item.get("window_handle") not in before_handles]
        if windows:
            break
        time.sleep(1)

    return {
        "ok": bool(windows),
        "pid": process.pid,
        "command": command,
        "visible_windows": windows,
        "visible_window_detected": bool(windows),
    }


class BrowserHelperHandler(BaseHTTPRequestHandler):
    server_version = "AIPoplineDesktopBrowserHelper/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"ok": True, "service": "ai-popline-desktop-browser-helper"})
            return
        if parsed.path == "/open":
            query = parse_qs(parsed.query)
            url = (query.get("url") or [""])[0]
            if not url:
                self._send_json({"ok": False, "error": "missing_url"}, status=400)
                return
            user_data_dir_raw = (query.get("user_data_dir") or [""])[0]
            user_data_dir = Path(user_data_dir_raw) if user_data_dir_raw else None
            result = open_visible_chrome(url=url, user_data_dir=user_data_dir)
            self._send_json(result)
            return
        self._send_json({"ok": False, "error": "not_found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("desktop browser helper must bind to localhost only")
    server = ThreadingHTTPServer((host, port), BrowserHelperHandler)
    print(f"Desktop browser helper listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Popline desktop browser helper")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=int(os.getenv("AI_POPLINE_BROWSER_HELPER_PORT", DEFAULT_PORT)))
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
