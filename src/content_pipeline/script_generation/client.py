from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from content_pipeline.errors import ConfigError, ExternalToolError
from content_pipeline.settings import Settings

__all__ = ["OpenAICompatibleScriptClient"]


class OpenAICompatibleScriptClient:
    def __init__(self, settings: Settings, *, timeout: int | None = None):
        self.base_url = settings.script_llm_base_url or settings.router_llm_base_url
        self.api_key = settings.script_llm_api_key or settings.router_llm_api_key
        self.model = settings.script_llm_model or settings.router_llm_model
        self.timeout = settings.script_llm_timeout_seconds if timeout is None else timeout

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.35,
        response_format: dict[str, Any] | None = None,
        label: str = "script generation",
    ) -> str:
        if not self.base_url or not self.model:
            raise ConfigError(f"script LLM is not configured for {label}")
        url = self.base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ExternalToolError(f"{label} LLM returned HTTP {exc.code}: {detail}") from exc
        except OSError as exc:
            raise ExternalToolError(f"{label} LLM request failed: {exc}") from exc
        try:
            result = json.loads(raw)
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ExternalToolError(f"{label} LLM returned an invalid response") from exc
        if not isinstance(content, str) or not content.strip():
            raise ExternalToolError(f"{label} LLM returned empty content")
        return content.strip()
