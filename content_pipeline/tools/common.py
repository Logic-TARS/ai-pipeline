from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from os import environ
from pathlib import Path
from typing import Mapping

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
) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(retries + 1):
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env={**environ, **env} if env is not None else None,
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
