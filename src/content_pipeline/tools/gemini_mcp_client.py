from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

__all__ = ["GeminiMcpClient", "generate_many"]


class GeminiMcpClient:
    def __init__(self, skill_dir: Path, output_dir: Path, timeout: int = 240):
        self.skill_dir = skill_dir
        self.output_dir = output_dir
        self.timeout = timeout
        self.proc: subprocess.Popen[str] | None = None
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=100)

    def __enter__(self) -> GeminiMcpClient:
        env = os.environ.copy()
        env["OUTPUT_DIR"] = str(self.output_dir)
        self.proc = subprocess.Popen(
            ["node", "src/mcp-server.js"],
            cwd=str(self.skill_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-pipeline", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})
        return self

    def __exit__(self, *_args: object) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def list_tools(self) -> dict[str, Any]:
        return self._request("tools/list", {})

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, timeout: int | None = None
    ) -> dict[str, Any]:
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout or 60,
        )

    def generate_image(self, prompt: str, full_size: bool = True, new_session: bool = False) -> Path:
        before = set(self.output_dir.glob("*"))
        result = self.call_tool(
            "gemini_generate_image",
            {
                "prompt": prompt,
                "newSession": new_session,
                "referenceImages": [],
                "fullSize": full_size,
                "timeout": self.timeout * 1000,
            },
            timeout=self.timeout + 30,
        )
        text = "\n".join(
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )
        if result.get("isError"):
            raise RuntimeError(text or "gemini_generate_image failed")
        path = _extract_path(text)
        if path:
            return _guard_generated_image(path, self.output_dir)
        after = sorted(
            [p for p in self.output_dir.glob("*") if p not in before and p.is_file() and not p.is_symlink()],
            key=lambda p: p.stat().st_mtime,
        )
        if after:
            return _guard_generated_image(after[-1], self.output_dir)
        raise RuntimeError(f"Gemini reported success but no image file was found. Response: {text}")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()

    def _request(self, method: str, params: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
        assert self.proc and self.proc.stdin
        request_id = int(time.time() * 1000)
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n"
        )
        self.proc.stdin.flush()
        deadline = time.time() + (timeout or 30)
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            try:
                line = self._stdout.get(timeout=min(0.1, remaining))
            except queue.Empty as exc:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"Gemini MCP exited early: {self._stderr_text()}") from exc
                continue
            if line is None:
                raise RuntimeError(f"Gemini MCP exited early: {self._stderr_text()}")
            payload = json.loads(line)
            if payload.get("id") != request_id:
                continue
            if "error" in payload:
                raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
            return payload.get("result", {})
        raise TimeoutError(f"Gemini MCP request timed out: {method}. stderr: {self._stderr_text()}")

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self._stdout.put(line)
        self._stdout.put(None)

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def _stderr_text(self) -> str:
        return "\n".join(self._stderr) or "no stderr output"


def _extract_path(text: str) -> Path | None:
    matches = re.findall(r"[A-Za-z]:\\[^\n\r]+?\.(?:png|jpg|jpeg|webp)", text)
    return Path(matches[-1]) if matches else None


def _guard_generated_image(path: Path, output_dir: Path) -> Path:
    resolved_output_dir = output_dir.resolve()
    resolved_path = path.resolve()
    if path.is_symlink() or not resolved_path.is_file() or resolved_path.parent != resolved_output_dir:
        raise RuntimeError(f"Gemini reported an image outside output_dir: {path}")
    return resolved_path


def generate_many(
    skill_dir: Path,
    output_dir: Path,
    prompt: str,
    count: int,
    timeout: int,
    full_size: bool = True,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    with GeminiMcpClient(skill_dir=skill_dir, output_dir=output_dir, timeout=timeout) as client:
        for index in range(1, count + 1):
            image = client.generate_image(
                f"{prompt}\n\nImage {index} of {count}. Generate only this panel.",
                full_size=full_size,
                new_session=index == 1,
            )
            target = output_dir / f"{index:02d}{image.suffix.lower()}"
            if image.resolve() != target.resolve():
                shutil.copy2(image, target)
            results.append(target)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Call gemini-skill MCP image generation")
    parser.add_argument("--skill-dir", type=Path, default=Path(r"G:\Job\gemini-skill"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    paths = generate_many(args.skill_dir, args.output_dir, args.prompt, args.count, args.timeout)
    print(json.dumps([str(path) for path in paths], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
