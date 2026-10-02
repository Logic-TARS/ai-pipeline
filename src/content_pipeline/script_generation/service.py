from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal

from content_pipeline.errors import ConfigError
from content_pipeline.script_generation.client import OpenAICompatibleScriptClient
from content_pipeline.script_generation.models import (
    GenerationAttempt,
    ScriptFact,
    ScriptGenerationAudit,
    ScriptGenerationResult,
    ScriptPlan,
    StructuredFacts,
)
from content_pipeline.script_generation.prompts import (
    AI_PROMPT_VERSION,
    DRAFT_PROMPT_VERSION,
    FINANCE_PROMPT_VERSION,
    PLAN_PROMPT_VERSION,
    REPAIR_PROMPT_VERSION,
    build_draft_prompts,
    build_plan_prompts,
    build_repair_prompts,
)
from content_pipeline.script_generation.quality import extract_number_tokens, validate_script
from content_pipeline.settings import Settings

__all__ = ["ScriptGenerationService", "build_structured_facts", "validate_plan"]

FailurePolicy = Literal["fail", "validated_rule_fallback"]
ContentKind = Literal["ai_briefing", "finance", "finance_multi_asset"]
_NON_FACT_KEYS = {"fallback_script", "fallback_error", "prompt_version", "script_mode", "script_writer"}


class ScriptGenerationService:
    def __init__(self, settings: Settings, *, client: OpenAICompatibleScriptClient | None = None):
        self.client = client or OpenAICompatibleScriptClient(settings)

    def generate(
        self,
        *,
        content_type: ContentKind,
        material: dict[str, Any],
        fallback_script: str | None,
        failure_policy: FailurePolicy = "fail",
        repair_attempts: int = 1,
        on_attempt: Callable[[GenerationAttempt], None] | None = None,
    ) -> ScriptGenerationResult:
        facts = build_structured_facts(content_type, material)
        version = AI_PROMPT_VERSION if content_type == "ai_briefing" else FINANCE_PROMPT_VERSION
        attempts: list[GenerationAttempt] = []
        plan: ScriptPlan | None = None
        last_error: Exception | None = None
        failed_stage: Literal["plan", "draft", "repair"] = "plan"
        try:
            system, user = build_plan_prompts(facts)
            raw_plan = self.client.complete(
                system_prompt=system,
                user_prompt=user,
                temperature=0.2,
                response_format={"type": "json_object"},
                label=f"{content_type} script plan",
            )
            plan = _parse_plan(raw_plan)
            validate_plan(plan, facts)
            _append_attempt(
                attempts,
                GenerationAttempt(stage="plan", index=0, prompt_version=PLAN_PROMPT_VERSION, output=raw_plan),
                on_attempt,
            )
            failed_stage = "draft"
            system, user = build_draft_prompts(facts, plan)
            script = _clean_script(
                self.client.complete(
                    system_prompt=system,
                    user_prompt=user,
                    temperature=0.4,
                    label=f"{content_type} script draft",
                )
            )
            report = validate_script(script, facts, plan=plan)
            _append_attempt(
                attempts,
                GenerationAttempt(
                    stage="draft",
                    index=0,
                    prompt_version=DRAFT_PROMPT_VERSION,
                    output=script,
                    quality_report=report,
                ),
                on_attempt,
            )
            for index in range(1, repair_attempts + 1):
                if report.passed and not report.warnings:
                    break
                failed_stage = "repair"
                issues = [issue.model_dump(mode="json") for issue in (report.errors or report.warnings)]
                system, user = build_repair_prompts(facts, plan, script, issues)
                script = _clean_script(
                    self.client.complete(
                        system_prompt=system,
                        user_prompt=user,
                        temperature=0.25,
                        label=f"{content_type} script repair",
                    )
                )
                report = validate_script(script, facts, plan=plan)
                _append_attempt(
                    attempts,
                    GenerationAttempt(
                        stage="repair",
                        index=index,
                        prompt_version=REPAIR_PROMPT_VERSION,
                        output=script,
                        quality_report=report,
                    ),
                    on_attempt,
                )
            if report.passed:
                mode = "llm_repaired" if attempts[-1].stage == "repair" else "llm"
                return ScriptGenerationResult(
                    script=script,
                    audit=ScriptGenerationAudit(
                        generation_mode=mode,
                        prompt_version=version,
                        plan=plan,
                        attempts=attempts,
                        quality_report=report,
                    ),
                )
            last_error = ConfigError(_quality_error(report))
        except Exception as exc:
            last_error = exc
            _append_attempt(
                attempts,
                GenerationAttempt(
                    stage=failed_stage,
                    index=sum(attempt.stage == failed_stage for attempt in attempts),
                    prompt_version=_stage_version(failed_stage),
                    error=str(exc),
                ),
                on_attempt,
            )
        if failure_policy == "validated_rule_fallback" and fallback_script:
            fallback = _clean_script(fallback_script)
            report = validate_script(fallback, facts, plan=None)
            _append_attempt(
                attempts,
                GenerationAttempt(
                    stage="fallback",
                    index=0,
                    prompt_version=version,
                    output=fallback,
                    quality_report=report,
                ),
                on_attempt,
            )
            if report.passed:
                return ScriptGenerationResult(
                    script=fallback,
                    audit=ScriptGenerationAudit(
                        generation_mode="validated_rule_fallback",
                        prompt_version=version,
                        plan=plan,
                        attempts=attempts,
                        quality_report=report,
                        fallback_reason=str(last_error) if last_error else None,
                    ),
                )
        raise ConfigError(f"{content_type} script generation failed: {last_error}") from last_error

    def validate_rule(
        self,
        *,
        content_type: ContentKind,
        material: dict[str, Any],
        script: str,
    ) -> ScriptGenerationResult:
        facts = build_structured_facts(content_type, material)
        cleaned = _clean_script(script)
        report = validate_script(cleaned, facts, plan=None)
        if not report.passed:
            raise ConfigError(_quality_error(report))
        version = AI_PROMPT_VERSION if content_type == "ai_briefing" else FINANCE_PROMPT_VERSION
        attempt = GenerationAttempt(
            stage="fallback", index=0, prompt_version=version, output=cleaned, quality_report=report
        )
        return ScriptGenerationResult(
            script=cleaned,
            audit=ScriptGenerationAudit(
                generation_mode="rule",
                prompt_version=version,
                attempts=[attempt],
                quality_report=report,
            ),
        )


def validate_plan(plan: ScriptPlan, facts: StructuredFacts) -> None:
    fact_ids = {fact.id for fact in facts.facts}
    selected = set(plan.required_facts)
    unknown = ({plan.main_fact_id} | selected) - fact_ids
    if unknown:
        raise ConfigError(f"script plan references unknown fact ids: {', '.join(sorted(unknown))}")
    required = {fact.id for fact in facts.facts if fact.required}
    missing = required - selected
    if missing:
        raise ConfigError(f"script plan omitted required fact ids: {', '.join(sorted(missing))}")
    if plan.main_fact_id not in selected:
        raise ConfigError("script plan main_fact_id must also appear in required_facts")


def build_structured_facts(content_type: ContentKind, material: dict[str, Any]) -> StructuredFacts:
    clean = {key: value for key, value in material.items() if key not in _NON_FACT_KEYS}
    if content_type == "ai_briefing":
        facts = _ai_facts(clean)
    elif content_type == "finance":
        facts = _finance_facts(clean)
    else:
        facts = _multi_asset_facts(clean)
    if not facts:
        raise ConfigError(f"{content_type} material contains no usable facts")
    return StructuredFacts(content_type=content_type, facts=facts)


def _ai_facts(material: dict[str, Any]) -> list[ScriptFact]:
    facts: list[ScriptFact] = []
    summary = str(material.get("summary") or material.get("title") or "").strip()
    if summary:
        facts.append(_fact("ai.summary", "summary", summary, required=True, kind="summary"))
    date_text = str(material.get("date_text") or material.get("date") or "").strip()
    if date_text:
        facts.append(_fact("ai.date", "context", date_text, kind="context"))
    sections = (
        ("focus", "focus_sentences", True),
        ("frontier", "frontier_sentences", False),
        ("quick", "quick_items", False),
        ("conclusion", "conclusion_sentences", False),
    )
    for section, key, required_first in sections:
        for index, value in enumerate(material.get(key, []) or [], start=1):
            text = str(value).strip()
            if text:
                facts.append(
                    _fact(
                        f"ai.{section}.{index}",
                        section,
                        text,
                        required=required_first and index <= 2,
                        kind="ai",
                    )
                )
    return facts


def _finance_facts(material: dict[str, Any]) -> list[ScriptFact]:
    facts: list[ScriptFact] = []
    summary = str(material.get("summary") or material.get("index_summary") or "").strip()
    if summary:
        facts.append(_fact("finance.summary", "summary", summary, required=True, kind="summary"))
    publication_date = str(material.get("publication_date") or "").strip()
    if publication_date:
        facts.append(_fact("finance.date", "context", publication_date, kind="context"))
    for index, row in enumerate(material.get("indices", []) or [], start=1):
        if not isinstance(row, (list, tuple)) or not row:
            continue
        subject = str(row[0]).strip()
        text = " ".join(str(cell).strip() for cell in row if str(cell).strip())
        facts.append(
            _fact(
                f"finance.index.{index}",
                "indices",
                text,
                required=True,
                kind="index",
                subject=subject,
                direction=_direction(text),
                unit=_market_unit(text, default="point"),
            )
        )
    for index, row in enumerate(material.get("sector_rows", []) or [], start=1):
        if not isinstance(row, (list, tuple)) or not row:
            continue
        subject = str(row[0]).strip()
        text = " ".join(str(cell).strip() for cell in row if str(cell).strip())
        facts.append(
            _fact(
                f"finance.sector.{index}",
                "sectors",
                text,
                required=index <= 2,
                kind="sector",
                subject=subject,
                direction=_direction(text),
                unit=_market_unit(text, default="percent"),
            )
        )
    sector_text = str(material.get("sector_text") or "").strip()
    if sector_text:
        facts.append(_fact("finance.sector.context", "sectors", sector_text, kind="context"))
    for key, section, kind in (
        ("keywords", "signals", "context"),
        ("strategy", "strategy", "strategy"),
        ("valuation", "valuation", "context"),
        ("cross_asset", "cross_asset", "asset"),
    ):
        values = material.get(key) or []
        if isinstance(values, str):
            values = [values]
        for index, value in enumerate(values, start=1):
            text = str(value).strip()
            if text:
                facts.append(_fact(f"finance.{section}.{index}", section, text, kind=kind))
    facts.extend(_risk_facts(material, "finance"))
    return facts


def _multi_asset_facts(material: dict[str, Any]) -> list[ScriptFact]:
    facts: list[ScriptFact] = []
    modules = material.get("modules") if isinstance(material.get("modules"), dict) else material
    for index, (name, value) in enumerate(modules.items(), start=1):
        if name in _NON_FACT_KEYS or name in {"risk_note", "disclaimer"}:
            continue
        text = _compact_text(value)
        if text:
            facts.append(
                _fact(
                    f"asset.{_slug(name)}.{index}",
                    str(name)[:80],
                    text,
                    required=False,
                    kind="asset",
                    subject=str(name)[:120],
                )
            )
    facts.extend(_risk_facts(material, "asset"))
    if not any(fact.kind == "asset" for fact in facts):
        raise ConfigError("finance_multi_asset material contains no usable asset modules")
    return facts


def _risk_facts(material: dict[str, Any], prefix: str) -> list[ScriptFact]:
    result = []
    for key in ("risk_note", "disclaimer"):
        text = str(material.get(key) or "").strip()
        if text:
            result.append(_fact(f"{prefix}.{key}", "risk", text, required=True, kind="risk"))
    return result


def _fact(
    fact_id: str,
    section: str,
    text: str,
    *,
    required: bool = False,
    kind: str = "context",
    subject: str | None = None,
    direction: str | None = None,
    unit: str | None = None,
) -> ScriptFact:
    return ScriptFact(
        id=fact_id,
        section=section,
        text=text,
        required=required,
        numbers=sorted(extract_number_tokens(text)),
        entities=_entities(text)[:20],
        status_markers=_status_markers(text),
        kind=kind,
        subject=subject,
        direction=direction,
        unit=unit,
    )


def _entities(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}|[\u4e00-\u9fff]{2,10}", text)
    ignored = {"今日焦点", "前沿动态", "一句话快讯", "每日简报", "人工智能", "今天", "方面", "市场"}
    return list(dict.fromkeys(item for item in candidates if item not in ignored))


def _status_markers(text: str) -> list[str]:
    groups = {
        "planned": ("计划", "拟", "将", "预计", "准备"),
        "possible": ("可能", "有望", "或将", "传闻", "据称"),
        "testing": ("测试", "试点", "预览", "内测"),
        "completed": ("已发布", "已上线", "已确认", "正式发布", "正式上线"),
    }
    return [name for name, markers in groups.items() if any(marker in text for marker in markers)]


def _direction(text: str) -> str | None:
    if re.search(r"(?:下跌|跌|回落|走低|负增长)|-\d", text):
        return "down"
    if re.search(r"(?:上涨|涨|走高|上行|正增长)|\+\d", text):
        return "up"
    if any(marker in text for marker in ("持平", "平收")):
        return "flat"
    return None


def _market_unit(text: str, *, default: str) -> str:
    if "百分点" in text:
        return "percentage_point"
    if "%" in text or "百分比" in text:
        return "percent"
    if "点" in text:
        return "point"
    return default


def _compact_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:2000]
    if value in (None, {}, []):
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:2000]


def _slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug[:40] or "module"


def _parse_plan(raw: str) -> ScriptPlan:
    value = raw.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        return ScriptPlan.model_validate(json.loads(value))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ConfigError("script plan LLM returned invalid JSON") from exc


def _clean_script(script: str) -> str:
    return re.sub(r"\s+", "", script).strip()


def _quality_error(report) -> str:
    return "; ".join(f"{issue.code}: {issue.message}" for issue in report.errors)


def _append_attempt(
    attempts: list[GenerationAttempt],
    attempt: GenerationAttempt,
    callback: Callable[[GenerationAttempt], None] | None,
) -> None:
    attempts.append(attempt)
    if callback:
        callback(attempt)


def _stage_version(stage: str) -> str:
    return {
        "plan": PLAN_PROMPT_VERSION,
        "draft": DRAFT_PROMPT_VERSION,
        "repair": REPAIR_PROMPT_VERSION,
    }[stage]
