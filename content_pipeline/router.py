from __future__ import annotations

import json
import os
import urllib.request

from .models import RouteResult, TaskInput
from .settings import Settings


ROUTER_PROMPT = """Classify this content task.
Return only JSON with keys: content_type, topic, params.
Allowed content_type values: anime, finance, ai_briefing, ai_art, grouped_anime, japanese, unknown.
Task: {description}
"""


ANIME_KEYWORDS = ("动漫", "漫画", "二次元", "角色", "番剧", "anime", "comic")
FINANCE_KEYWORDS = ("金融", "财经", "股票", "基金", "宏观", "投资", "finance", "stock")
AI_BRIEFING_KEYWORDS = ("ai简报", "ai 简报", "ai资讯", "ai 资讯", "人工智能新闻", "ai briefing", "ai news")
AI_ART_KEYWORDS = ("ai绘画", "ai 绘画", "改图", "图片处理", "ai art", "image edit")
GROUPED_ANIME_KEYWORDS = ("分组动漫", "grouped anime", "图片组合")
JAPANESE_KEYWORDS = ("日语", "日文", "japanese")


def route_task(task: TaskInput, settings: Settings) -> RouteResult:
    if task.content_type:
        return RouteResult(
            content_type=task.content_type,
            topic=task.topic or task.description,
            params=task.params,
        )

    if settings.router_llm_base_url and settings.router_llm_api_key and settings.router_llm_model:
        try:
            return _route_with_openai_compatible(task, settings)
        except Exception:
            # The router must not break the pipeline when a cheap rule fallback can decide.
            pass

    return _route_with_rules(task)


def _route_with_rules(task: TaskInput) -> RouteResult:
    text = task.description.lower()
    if any(keyword.lower() in text for keyword in GROUPED_ANIME_KEYWORDS):
        content_type = "grouped_anime"
    elif any(keyword.lower() in text for keyword in JAPANESE_KEYWORDS):
        content_type = "japanese"
    elif any(keyword.lower() in text for keyword in AI_ART_KEYWORDS):
        content_type = "ai_art"
    elif any(keyword.lower() in text for keyword in AI_BRIEFING_KEYWORDS):
        content_type = "ai_briefing"
    elif any(keyword.lower() in text for keyword in ANIME_KEYWORDS):
        content_type = "anime"
    elif any(keyword.lower() in text for keyword in FINANCE_KEYWORDS):
        content_type = "finance"
    else:
        content_type = "unknown"
    return RouteResult(content_type=content_type, topic=task.topic or task.description, params=task.params)


def _route_with_openai_compatible(task: TaskInput, settings: Settings) -> RouteResult:
    url = settings.router_llm_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.router_llm_model,
        "messages": [
            {"role": "system", "content": "You are a strict JSON classification router."},
            {"role": "user", "content": ROUTER_PROMPT.format(description=task.description)},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.router_llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=int(os.getenv("ROUTER_LLM_TIMEOUT", "30"))) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return RouteResult.model_validate(json.loads(content))
