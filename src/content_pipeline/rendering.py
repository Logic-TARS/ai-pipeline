from __future__ import annotations

from typing import Any


def render_template(template: str, topic: str, params: dict[str, Any]) -> str:
    script = str(params.get("script") or params.get("copy") or topic)
    values = {"topic": topic, "script": script, **params}
    return template.format_map(_SafeDict(values))


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
