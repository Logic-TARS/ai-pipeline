from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from content_pipeline.settings import Settings

__all__ = ["TTSkillAuthError", "TTSkillClient", "TTSkillError"]

READ_ONLY_SKILLS = {
    "TTFUND_GOLD_INFO",
    "TTFUND_BOND_MARKET",
    "TTFUND_MACRO_DATA",
    "TTFUND_STOCK_PRICE_QUERY",
}
MAX_OUTPUT_BYTES = 5 * 1024 * 1024


class TTSkillError(RuntimeError):
    pass


class TTSkillAuthError(TTSkillError):
    pass


class TTSkillClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = shutil.which(settings.ttskill_command) or settings.ttskill_command

    def readiness(self) -> dict[str, Any]:
        try:
            payload = self._run(["status", "--json"], timeout=20)
        except TTSkillError as exc:
            return {"available": False, "authenticated": False, "installed_count": 0, "message": str(exc)}
        auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
        skills = payload.get("skills") if isinstance(payload.get("skills"), dict) else {}
        current_user = auth.get("current_user") if isinstance(auth.get("current_user"), dict) else {}
        return {
            "available": True,
            "authenticated": bool(auth.get("has_token")) and not bool(current_user.get("is_expired", False)),
            "installed_count": int(skills.get("installed_count") or 0),
            "message": "ttskill ready" if auth.get("has_token") else "run ttskill login on the server",
        }

    def invoke(self, skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if skill_id not in READ_ONLY_SKILLS:
            raise TTSkillError("skill is outside the read-only content allowlist")
        temporary_dir = self.settings.data_dir / "content-tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        body_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", prefix="ttskill-", dir=temporary_dir, delete=False
            ) as handle:
                json.dump(body, handle, ensure_ascii=False)
                body_path = Path(handle.name)
            payload = self._run(
                ["invoke", skill_id, "--action", "query", "--body", str(body_path)],
                timeout=self.settings.ttskill_timeout_seconds,
            )
        finally:
            if body_path is not None:
                body_path.unlink(missing_ok=True)
        if payload.get("code") != 0:
            self._raise_business_error(payload)
        data = payload.get("data")
        raw_result = data.get("raw_result") if isinstance(data, dict) else None
        body_result = raw_result.get("body") if isinstance(raw_result, dict) else None
        if not isinstance(body_result, dict):
            raise TTSkillError("ttskill returned no structured business result")
        return body_result

    def _run(self, arguments: list[str], *, timeout: int) -> dict[str, Any]:
        command = self._command(arguments)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise TTSkillError("ttskill command was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise TTSkillError("ttskill request timed out") from exc
        output = result.stdout.strip()
        diagnostic = f"{output}\n{result.stderr}".lower()
        if any(marker in diagnostic for marker in ("cli_login_required", "登录态失效", "token 失效")):
            raise TTSkillAuthError("ttskill 登录已失效，请在服务器运行 ttskill login")
        if result.returncode != 0:
            raise TTSkillError("ttskill request failed")
        if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise TTSkillError("ttskill response exceeded the safe size limit")
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise TTSkillError("ttskill returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TTSkillError("ttskill returned an invalid response")
        return payload

    def _command(self, arguments: list[str]) -> list[str]:
        executable = str(self.executable)
        if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable, *arguments]
        return [executable, *arguments]

    @staticmethod
    def _raise_business_error(payload: dict[str, Any]) -> None:
        message = str(payload.get("message") or "ttskill business request failed")
        lowered = message.lower()
        if any(marker in lowered for marker in ("cli_login_required", "登录", "token")):
            raise TTSkillAuthError("ttskill 登录已失效，请在服务器运行 ttskill login")
        raise TTSkillError(message[:300])
