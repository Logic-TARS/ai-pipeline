from __future__ import annotations

import json
import re
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any

from content_pipeline.ai_briefing_pipeline import build_90_second_briefing_script
from content_pipeline.content_studio.models import ContentDraft, CreateDraftInput, ResearchSource
from content_pipeline.content_studio.store import ContentDraftStore, DraftConflictError
from content_pipeline.content_studio.ttskill_client import TTSkillClient
from content_pipeline.finance_pipeline import extract_response
from content_pipeline.finance_script import (
    CONTENT_STUDIO_MAX_CHARS,
    CONTENT_STUDIO_MIN_CHARS,
    build_daily_markdown_script,
    build_structured_finance_script,
)
from content_pipeline.settings import Settings
from content_pipeline.tools.narrated_mpt_client import looks_like_file_reference

FINANCE_DISCLAIMER = "以上内容仅为市场信息整理，不构成投资建议。"
TEMPLATES = [
    {
        "template_id": "finance_90s",
        "label": "90 秒金融资讯口播",
        "description": "汇总黄金、债市、宏观和自选股票的最新只读数据，自动生成可审阅的90秒口播初稿。",
        "default_title": "今日金融资讯",
        "supports_focus_assets": True,
        "requires_finance_disclaimer": True,
        "target_chars": {"minimum": 350, "maximum": 500},
        "sources": ["黄金行情", "债市晴雨表", "中国宏观数据", "关注股票（可选）"],
    },
    {
        "template_id": "ai_briefing_90s",
        "label": "90 秒 AI 简报",
        "description": "读取 AI_BRIEFING_DIR 中最新的 article.md 和交接信息，自动生成可审阅的90秒 AI 简报口播初稿。",
        "default_title": "每日 AI 简报",
        "supports_focus_assets": False,
        "requires_finance_disclaimer": False,
        "target_chars": {"minimum": 350, "maximum": 500},
        "sources": ["最新 AI 简报文章与交接信息"],
    },
]


class ContentStudioService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = ContentDraftStore(settings.data_dir)
        self.client = TTSkillClient(settings)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="content-research")
        self._futures: dict[str, Future] = {}

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def bootstrap(self) -> dict[str, Any]:
        return {"templates": TEMPLATES, "ttskill": self.client.readiness(), "disclaimer": FINANCE_DISCLAIMER}

    def create(self, request: CreateDraftInput) -> ContentDraft:
        focus_assets = request.focus_assets if request.template_id == "finance_90s" else []
        sources = self._pending_sources(request.template_id, focus_assets)
        draft = self.store.create(
            template_id=request.template_id,
            title=request.title.strip(),
            focus_assets=focus_assets,
            research=sources,
        )
        self._queue_collection(draft.draft_id)
        return draft

    def refresh(self, draft_id: str, expected_revision: int) -> ContentDraft:
        draft = self.store.get(draft_id)
        if draft.revision != expected_revision:
            raise DraftConflictError("content draft changed; reload it before refreshing")
        draft.research = self._pending_sources(draft.template_id, draft.focus_assets)
        draft.status = "collecting"
        draft.research_error = None
        saved = self.store.save(draft, expected_revision=expected_revision)
        self._queue_collection(draft_id)
        return saved

    def update(self, draft_id: str, *, revision: int, title: str, script: str) -> ContentDraft:
        draft = self.store.get(draft_id)
        if draft.revision != revision:
            raise DraftConflictError("content draft changed; reload it before saving")
        draft.title = title.strip()
        draft.script = script.strip()
        return self.store.save(draft, expected_revision=revision)

    def register_video_task(self, draft_id: str, revision: int, task_id: str) -> ContentDraft:
        draft = self.store.get(draft_id)
        if draft.revision != revision:
            raise DraftConflictError("content draft changed; save the latest version before generating video")
        draft.video_task_ids.append(task_id)
        return self.store.save(draft, expected_revision=revision)

    def validate_for_video(self, draft: ContentDraft) -> list[str]:
        script = draft.script.strip()
        errors: list[str] = []
        if draft.status == "collecting":
            errors.append("最新资料仍在采集中，请完成资料核对后再生成视频")
        elif not any(source.status == "succeeded" for source in draft.research):
            errors.append("没有可供核对的最新资料，不能生成视频")
        if len(script) < 350 or len(script) > 500:
            errors.append(f"90 秒口播稿需要 350–500 字，当前为 {len(script)} 字")
        if looks_like_file_reference(script) or re.search(r"(?:[A-Za-z]:[\\/]|/home/).+\.(?:md|txt|json)", script):
            errors.append("口播稿不能是文件路径或包含本地文件引用")
        if any(marker in script for marker in ("请根据左侧", "待补充", "TODO", "{{", "}}")):
            errors.append("口播稿仍包含未完成的占位内容")
        if draft.template_id == "finance_90s" and "不构成投资建议" not in script:
            errors.append(f"口播稿必须包含风险提示：{FINANCE_DISCLAIMER}")
        if not draft.title.strip():
            errors.append("视频标题不能为空")
        return errors

    def collect_now(self, draft_id: str) -> None:
        draft = self.store.get(draft_id)
        results: dict[str, ResearchSource] = {}
        finance_fallback_sources: list[ResearchSource] = []
        if draft.template_id == "ai_briefing_90s":
            original = draft.research[0]
            try:
                results[original.source_id] = self._collect_ai_briefing_source(draft_id)
            except Exception as exc:
                results[original.source_id] = original.model_copy(
                    update={"status": "failed", "error": str(exc)[:300], "fetched_at": self._now()}
                )
        elif draft.template_id == "finance_90s":
            try:
                results["finance-daily"] = self._collect_finance_daily_source(draft_id)
            except Exception as exc:
                results["finance-daily"] = ResearchSource(
                    source_id="finance-daily",
                    label="当天基金日报",
                    skill_id="FINANCE_DAILY_MARKDOWN",
                    status="failed",
                    fetched_at=self._now(),
                    error=str(exc)[:300],
                )
                finance_fallback_sources = [
                    ResearchSource(source_id=source_id, label=label, skill_id=skill_id)
                    for source_id, label, skill_id, _body in self._source_requests(draft.focus_assets)
                ]
                requests = self._source_requests(draft.focus_assets)
                with ThreadPoolExecutor(max_workers=min(4, len(requests)), thread_name_prefix="ttskill") as pool:
                    futures = {
                        pool.submit(self._collect_source, draft_id, source_id, label, skill_id, body): source_id
                        for source_id, label, skill_id, body in requests
                    }
                    for future in as_completed(futures):
                        source_id = futures[future]
                        try:
                            results[source_id] = future.result()
                        except Exception as exc:
                            original = next(item for item in finance_fallback_sources if item.source_id == source_id)
                            results[source_id] = original.model_copy(
                                update={"status": "failed", "error": str(exc)[:300], "fetched_at": self._now()}
                            )
        else:
            requests = self._source_requests(draft.focus_assets)
            with ThreadPoolExecutor(max_workers=min(4, len(requests)), thread_name_prefix="ttskill") as pool:
                futures = {
                    pool.submit(self._collect_source, draft_id, source_id, label, skill_id, body): source_id
                    for source_id, label, skill_id, body in requests
                }
                for future in as_completed(futures):
                    source_id = futures[future]
                    try:
                        results[source_id] = future.result()
                    except Exception as exc:
                        original = next(item for item in draft.research if item.source_id == source_id)
                        results[source_id] = original.model_copy(
                            update={"status": "failed", "error": str(exc)[:300], "fetched_at": self._now()}
                        )

        def finish(current: ContentDraft) -> None:
            if current.template_id == "finance_90s":
                daily = results["finance-daily"]
                if daily.status == "succeeded":
                    current.research = [daily]
                else:
                    current.research = [daily] + [
                        results.get(item.source_id, item) for item in finance_fallback_sources
                    ]
            else:
                current.research = [results.get(item.source_id, item) for item in current.research]
            succeeded = sum(item.status == "succeeded" for item in current.research)
            failed = sum(item.status == "failed" for item in current.research)
            current.status = "ready" if succeeded and not failed else "partial" if succeeded else "failed"
            current.research_error = "部分资料获取失败，可刷新重试。" if succeeded and failed else None
            if not succeeded:
                current.research_error = (
                    "未找到可用的最新 AI 简报文章，请检查 AI_BRIEFING_DIR。"
                    if current.template_id == "ai_briefing_90s"
                    else "未能获取任何最新资料，请检查 ttskill 登录和网络状态。"
                )
            elif not current.script.strip():
                try:
                    current.script = self._generate_initial_script(current)
                    if current.template_id == "ai_briefing_90s" and current.title == "每日 AI 简报":
                        current.title = str(current.research[0].payload.get("title") or current.title)
                except Exception as exc:
                    warning = f"资料已就绪，但自动初稿生成失败：{str(exc)[:180]}"
                    current.research_error = (
                        f"{current.research_error} {warning}" if current.research_error else warning
                    )
                    if current.template_id == "finance_90s":
                        current.status = "failed"

        self.store.mutate(draft_id, finish)

    def _queue_collection(self, draft_id: str) -> None:
        active = self._futures.get(draft_id)
        if active and not active.done():
            return
        self._futures[draft_id] = self.executor.submit(self.collect_now, draft_id)

    def _collect_source(
        self, draft_id: str, source_id: str, label: str, skill_id: str, body: dict[str, Any]
    ) -> ResearchSource:
        business = self.client.invoke(skill_id, body)
        normalized = self._normalize(skill_id, business)
        self.store.write_source(source_id=source_id, draft_id=draft_id, payload=normalized)
        return ResearchSource(
            source_id=source_id,
            label=label,
            skill_id=skill_id,
            status="succeeded",
            fetched_at=self._now(),
            data_as_of=self._find_as_of(normalized),
            summary=self._summary(skill_id, normalized),
            payload=normalized,
        )

    def _collect_finance_daily_source(self, draft_id: str) -> ResearchSource:
        source_root = self.settings.finance_md_dir.expanduser().resolve()
        if not source_root.is_dir():
            raise FileNotFoundError("finance markdown directory does not exist")
        today = datetime.now().date().isoformat()
        candidates = sorted(
            source_root.glob(f"{today}*.md"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(f"no finance markdown found for today: {today}")
        source = candidates[0]
        response = extract_response(source.read_text(encoding="utf-8-sig"))
        payload = {"date": today, "path": str(source), "response": response[:80_000]}
        self.store.write_source(draft_id=draft_id, source_id="finance-daily", payload=payload)
        return ResearchSource(
            source_id="finance-daily",
            label="当天基金日报",
            skill_id="FINANCE_DAILY_MARKDOWN",
            status="succeeded",
            fetched_at=self._now(),
            data_as_of=today,
            summary=f"{today} · {source.name}",
            payload=payload,
        )

    def _collect_ai_briefing_source(self, draft_id: str) -> ResearchSource:
        source_root = self.settings.ai_briefing_dir.expanduser().resolve()
        if not source_root.is_dir():
            raise FileNotFoundError("AI_BRIEFING_DIR does not exist")
        today = datetime.now().strftime("%Y%m%d")
        candidates = sorted(
            (
                path
                for path in source_root.iterdir()
                if path.is_dir() and re.fullmatch(r"\d{8}", path.name) and path.name <= today
            ),
            key=lambda path: path.name,
            reverse=True,
        )
        day_dir = next((path for path in candidates if (path / "article.md").is_file()), None)
        if day_dir is None:
            raise FileNotFoundError("no dated AI briefing article.md was found")
        article_path = day_dir / "article.md"
        if article_path.stat().st_size > 250_000:
            raise ValueError("AI briefing article exceeds the safe size limit")
        article = article_path.read_text(encoding="utf-8-sig")
        handoff_path = day_dir / "video_handoff.json"
        try:
            handoff = json.loads(handoff_path.read_text(encoding="utf-8")) if handoff_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            handoff = {}
        title_match = re.search(r"(?m)^标题:\s*(.+)$", article)
        summary_match = re.search(r"(?m)^摘要:\s*(.+)$", article)
        title = str(handoff.get("title") or (title_match.group(1).strip() if title_match else "每日 AI 简报"))
        normalized = {
            "date": day_dir.name,
            "title": title,
            "summary": summary_match.group(1).strip() if summary_match else "",
            "article_markdown": article[:50_000],
            "handoff_created_at": handoff.get("created_at"),
            "platforms": handoff.get("platforms") or [],
        }
        self.store.write_source(draft_id=draft_id, source_id="ai-briefing", payload=normalized)
        return ResearchSource(
            source_id="ai-briefing",
            label="最新 AI 简报文章",
            skill_id="AI_BRIEFING_HANDOFF",
            status="succeeded",
            fetched_at=self._now(),
            data_as_of=day_dir.name,
            summary=f"{day_dir.name} · {title}",
            payload=normalized,
        )

    def _pending_sources(self, template_id: str, focus_assets: list[str]) -> list[ResearchSource]:
        if template_id == "ai_briefing_90s":
            return [
                ResearchSource(
                    source_id="ai-briefing",
                    label="最新 AI 简报文章",
                    skill_id="AI_BRIEFING_HANDOFF",
                )
            ]
        if template_id == "finance_90s":
            return [
                ResearchSource(
                    source_id="finance-daily",
                    label="当天基金日报",
                    skill_id="FINANCE_DAILY_MARKDOWN",
                )
            ]
        return [
            ResearchSource(source_id=source_id, label=label, skill_id=skill_id)
            for source_id, label, skill_id, _body in self._source_requests(focus_assets)
        ]

    def _source_requests(self, focus_assets: list[str]):
        now = datetime.now(UTC).date()
        requests = [
            ("gold", "黄金行情", "TTFUND_GOLD_INFO", {"query_scope": "all"}),
            ("bond", "债市晴雨表", "TTFUND_BOND_MARKET", {}),
            (
                "macro-cn",
                "中国宏观数据",
                "TTFUND_MACRO_DATA",
                {
                    "region": "cn",
                    "categories": "cpi,ppi,pmi,m2,afre,usdcny",
                    "start_date": (now - timedelta(days=180)).isoformat(),
                    "end_date": now.isoformat(),
                },
            ),
        ]
        requests.extend(
            (f"stock-{index}", f"股票 · {asset}", "TTFUND_STOCK_PRICE_QUERY", {"query": asset})
            for index, asset in enumerate(focus_assets, start=1)
        )
        return requests

    def _generate_initial_script(self, draft: ContentDraft) -> str:
        if draft.template_id == "ai_briefing_90s":
            source = next(item for item in draft.research if item.status == "succeeded")
            article = str(source.payload.get("article_markdown") or "")
            date = str(source.payload.get("date") or datetime.now().strftime("%Y%m%d"))
            script = build_90_second_briefing_script(article, date)
            if not 350 <= len(script) <= 500:
                raise ValueError(f"AI 简报初稿长度不合规：{len(script)} 字")
            return script
        return self._build_finance_initial_script(draft)

    def _build_finance_initial_script(self, draft: ContentDraft) -> str:
        sources = {item.source_id: item.payload for item in draft.research if item.status == "succeeded"}
        daily = sources.get("finance-daily")
        if daily:
            return build_daily_markdown_script(
                str(daily.get("response") or ""),
                str(daily.get("date") or datetime.now().date().isoformat()),
                min_chars=CONTENT_STUDIO_MIN_CHARS,
                max_chars=CONTENT_STUDIO_MAX_CHARS,
            )
        return build_structured_finance_script(sources, disclaimer=FINANCE_DISCLAIMER)

    @classmethod
    def _normalize(cls, skill_id: str, business: dict[str, Any]) -> dict[str, Any]:
        root = business.get("data") if isinstance(business.get("data"), dict) else business
        if skill_id == "TTFUND_BOND_MARKET":
            modules = root.get("module_1") if isinstance(root, dict) else None
            module = modules[0] if isinstance(modules, list) and modules and isinstance(modules[0], dict) else {}
            return cls._compact(
                {
                    "update_time": module.get("updateTime") or root.get("updateTime"),
                    "markdown": module.get("markdown"),
                    "text_summary": module.get("textSummary"),
                    "market": module.get("orgData"),
                }
            )
        if skill_id == "TTFUND_MACRO_DATA" and isinstance(root, dict):
            frequencies = []
            for frequency in root.get("frequencies") or []:
                if not isinstance(frequency, dict):
                    continue
                records = frequency.get("记录") if isinstance(frequency.get("记录"), list) else []
                frequencies.append({**frequency, "记录": records[-8:]})
            return cls._compact({**root, "frequencies": frequencies})
        return cls._compact(root if isinstance(root, dict) else business)

    @classmethod
    def _compact(cls, value: Any, depth: int = 0) -> Any:
        if depth >= 6:
            return "[内容已折叠]"
        if isinstance(value, dict):
            return {str(key): cls._compact(item, depth + 1) for key, item in list(value.items())[:80]}
        if isinstance(value, list):
            return [cls._compact(item, depth + 1) for item in value[:30]]
        if isinstance(value, str) and len(value) > 5000:
            return value[:5000] + "…"
        return value

    @staticmethod
    def _find_as_of(payload: dict[str, Any]) -> str | None:
        for key in ("as_of", "update_time", "updateTime", "snapshot_time", "date", "quote_timestamp"):
            value = payload.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return str(value)
        return None

    @staticmethod
    def _summary(skill_id: str, payload: dict[str, Any]) -> str:
        if skill_id == "TTFUND_BOND_MARKET":
            return str(payload.get("text_summary") or "已获取最新债市晴雨表")[:1000]
        labels = {
            "TTFUND_GOLD_INFO": "已获取黄金行情、宏观风险指标和黄金资讯",
            "TTFUND_MACRO_DATA": "已获取最近六个月中国宏观数据",
            "TTFUND_STOCK_PRICE_QUERY": "已获取最新股票行情",
        }
        return labels.get(skill_id, "已获取最新资料")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
