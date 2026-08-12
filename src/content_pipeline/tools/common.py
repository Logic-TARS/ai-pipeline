from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from os import environ
from pathlib import Path

from content_pipeline.errors import ExternalToolError

NETWORK_RETRY_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "network",
    "temporarily",
    "429",
    "502",
    "503",
    "504",
)


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    retries: int = 0,
    env: Mapping[str, str] | None = None,
    on_output: Callable[[str, str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(retries + 1):
        result = _run_once(
            command,
            cwd=cwd,
            timeout=timeout,
            env=env,
            on_output=on_output,
        )
        if result.returncode == 0:
            return result
        last = result
        error_text = (result.stderr or result.stdout or "").lower()
        if attempt >= retries or not any(marker in error_text for marker in NETWORK_RETRY_MARKERS):
            break
        time.sleep(2 * (attempt + 1))
    assert last is not None
    stdout = last.stdout.strip()
    stderr = last.stderr.strip()
    details = "\n".join(
        part for part in (f"stdout:\n{stdout}" if stdout else "", f"stderr:\n{stderr}" if stderr else "") if part
    )
    raise ExternalToolError(details or f"command failed: {command}")


def _run_once(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: Mapping[str, str] | None,
    on_output: Callable[[str, str], None] | None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and optionally expose complete output lines while it is still running."""
    if on_output is None:
        return subprocess.run(
            list(command),
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**environ, **env} if env is not None else None,
        )

    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**environ, **env} if env is not None else None,
    )
    output: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def read_stream(name: str, stream) -> None:
        assert stream is not None
        for line in iter(stream.readline, ""):
            output.put((name, line))
        output.put((name, None))

    readers = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    stdout: list[str] = []
    stderr: list[str] = []
    closed_streams = 0
    deadline = time.monotonic() + timeout
    try:
        while closed_streams < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(command), timeout)
            try:
                name, line = output.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if line is None:
                closed_streams += 1
                continue
            if name == "stdout":
                stdout.append(line)
            else:
                stderr.append(line)
            on_output(name, line)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    finally:
        for reader in readers:
            reader.join(timeout=1)

    return subprocess.CompletedProcess(list(command), process.wait(), "".join(stdout), "".join(stderr))
