from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .errors import ConfigError
from .finance_script import FinanceScriptError, build_daily_markdown_script
from .media_validation import validate_video
from .models import FinanceParams, PipelineStep, PublishTarget
from .pipelines.registry import PipelineContext, PipelineMeta, register
from .publish_policy import resolve_publish_plan
from .publishing import publish_generated_video
from .script_generation import ScriptGenerationService
from .script_generation.audit import persist_script_audit, record_script_attempt_event
from .tools.finance_mpt_client import call_finance_mpt
from .tools.narrated_mpt_client import looks_like_file_reference, validate_spoken_subtitle

__all__ = [
    "DISCLAIMER",
    "FINANCE_NARRATION_MAX_CHARS",
    "FINANCE_SECTION_LABELS",
    "RISK_NOTE",
    "build_90_second_script",
    "build_finance_script_material",
    "extract_response",
    "run_finance_pipeline",
    "select_daily_markdown",
    "validate_finance_narration",
]

DISCLAIMER = "以上内容仅为市场信息整理和个人观点，不构成任何投资建议。"
RISK_NOTE = "面对市场波动，请结合自身投资期限、仓位水平和风险承受能力审慎决策。"
FINANCE_NARRATION_MAX_CHARS = 450
FINANCE_SECTION_LABELS = (
    "顶部摘要",
    "四大指数",
    "四指数行情",
    "四指数表格",
    "板块轮动",
    "估值水位",
    "今日关键词",
    "三个信号",
    "核心信号",
    "我的解读",
    "策略建议",
    "投资建议",
    "黄金债市",
    "黄金",
    "债券",
)


RESPONSE_HEADING_RE = re.compile(r"(?im)^##\s+Response\s*$")


def _has_response_section(path: Path) -> bool:
    try:
        return bool(RESPONSE_HEADING_RE.search(path.read_text(encoding="utf-8-sig")))
    except OSError:
        return False


def select_daily_markdown(source_dir: Path, requested_date: str = "auto", *, today: date | None = None) -> Path:
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ConfigError(f"finance markdown directory not found: {source_dir}")

    current = today or date.today()
    if requested_date == "auto":
        dates = [current, current - timedelta(days=1)]
    else:
        try:
            dates = [datetime.strptime(requested_date.replace("/", "-"), "%Y-%m-%d").date()]
        except ValueError as exc:
            raise ConfigError("finance params.date must be 'auto' or YYYY-MM-DD") from exc

    for candidate_date in dates:
        prefix = candidate_date.isoformat()
        candidates = sorted(
            source_dir.glob(f"{prefix}*.md"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for candidate in candidates:
            if requested_date != "auto" or _has_response_section(candidate):
                return candidate
    if requested_date == "auto":
        candidates = sorted(
            source_dir.glob("*.md"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for candidate in candidates:
            if _has_response_section(candidate):
                return candidate
    wanted = ", ".join(item.isoformat() for item in dates)
    raise ConfigError(f"no finance markdown with a '## Response' section found for: {wanted}")


def extract_response(markdown: str) -> str:
    match = RESPONSE_HEADING_RE.search(markdown)
    if not match:
        raise ConfigError("finance markdown is missing a '## Response' section")
    response = markdown[match.end() :].strip()
    if not response:
        raise ConfigError("finance markdown '## Response' section is empty")
    has_report_content = bool(re.search(r"(?m)^\s*(?:\||#{2,4}\s+|\*\*一句话总结|一句话总结[：:])", response))
    if not has_report_content and ("文件路径" in response or looks_like_file_reference(response)):
        raise ConfigError("finance markdown response contains a file reference instead of report content")
    return response


def _clean_markdown(value: str) -> str:
    value = re.sub(r"!\[[^]]*]\([^)]*\)", "", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    value = re.sub(r"[`*_>#]", "", value)
    value = re.sub(r"^[|\s]+|[|\s]+$", "", value)
    value = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%+\-.,，。；：:、（）()/$≈]", "", value)
    return re.sub(r"\s+", "", value).strip("，。； ")


def _section(markdown: str, *keywords: str) -> str:
    candidates = re.finditer(r"(?m)^(?:#{2,4}\s+(.+?)|\*\*(.+?)\*\*)\s*$", markdown)
    headings = []
    for heading in candidates:
        title = _clean_markdown(heading.group(1) or heading.group(2))
        if any(label in title for label in FINANCE_SECTION_LABELS):
            headings.append((heading, title))
    for index, (heading, title) in enumerate(headings):
        if any(keyword in title for keyword in keywords):
            end = headings[index + 1][0].start() if index + 1 < len(headings) else len(markdown)
            return markdown[heading.end() : end].strip()
    return ""


def _table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.strip().startswith("|") or re.search(r"\|\s*:?-{2,}", line):
            continue
        cells = [_clean_markdown(cell) for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] not in {"指数", "板块", "品种"}:
            rows.append(cells)
    return rows


def _summary_table(markdown: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in _table_rows(markdown):
        if len(row) < 2 or row[0] in {"模块", "项目", "类别"}:
            continue
        values[_clean_markdown(row[0])] = _clean_markdown(row[1])
    return values


def _summary_value(values: dict[str, str], *keywords: str) -> str:
    for label, value in values.items():
        if any(keyword in label for keyword in keywords):
            return value
    return ""


def _first_sentence(value: str) -> str:
    cleaned = _clean_markdown(value)
    parts = re.split(r"(?<=[。！？])", cleaned)
    return next((part.strip() for part in parts if part.strip()), cleaned)


def _first_sentences(value: str, limit: int) -> list[str]:
    cleaned = _clean_markdown(value)
    return [part.strip() for part in re.split(r"(?<=[。！？])", cleaned) if part.strip()][:limit]


def _trim_complete(value: str, limit: int) -> str:
    value = value.strip("，。； ")
    if len(value) <= limit:
        return value
    clipped = value[:limit]
    stops = [clipped.rfind(mark) for mark in "。！？；"]
    stop = max(stops)
    if stop >= max(120, limit - 100):
        return clipped[: stop + 1].strip()
    return clipped.rstrip("，；： ") + "。"


def _validate_finance_script(script: str) -> None:
    if not 300 <= len(script) <= 600:
        raise ConfigError(f"finance narration must contain 300-600 characters; generated {len(script)} characters")
    _validate_finance_script_safety(script)


def _validate_finance_script_safety(script: str) -> None:
    normalized = script.replace(" ", "")
    if (
        looks_like_file_reference(normalized)
        or "文件路径" in script
        or re.search(r"(?:^|[：:])(?:~|[A-Za-z]:)[/\\].+\.(?:md|txt|json|srt)", script, re.IGNORECASE)
    ):
        raise ConfigError("finance narration contains a file reference instead of spoken content")
    if not all(marker in script for marker in ("指数", "板块")):
        raise ConfigError("finance narration is missing required index or sector market information")


def build_finance_script_material(response: str, publication_date: str) -> dict[str, object]:
    summary_values = _summary_table(response)
    material = {
        "publication_date": publication_date,
        "summary": _summary_value(summary_values, "盘面定性", "顶部摘要", "一句话总结"),
        "indices": _table_rows(_section(response, "四大指数", "四指数行情", "四指数表格"))[:4],
        "index_summary": _summary_value(summary_values, "四大指数", "四指数"),
        "sector_rows": [
            row
            for row in _table_rows(_section(response, "板块轮动"))
            if not any(cell in {"代表个股", "涨幅", "跌幅", "涨跌幅"} for cell in row[1:])
        ][:8],
        "sector_text": _clean_markdown(_section(response, "板块轮动"))[:1000],
        "sector_summary": _summary_value(summary_values, "板块轮动"),
        "keywords": _first_sentences(_section(response, "今日关键词", "三个信号", "核心信号"), 4),
        "keyword_summary": _summary_value(summary_values, "今日关键词", "三个信号", "核心信号"),
        "strategy": _first_sentences(_section(response, "我的解读", "策略建议", "投资建议"), 4),
        "strategy_summary": _summary_value(summary_values, "我的解读", "策略建议", "投资建议"),
        "valuation": _clean_markdown(_section(response, "估值水位"))[:240],
        "valuation_summary": _summary_value(summary_values, "估值水位", "估值"),
        "cross_asset": _clean_markdown(_section(response, "黄金债市", "黄金", "债券"))[:240],
        "cross_asset_summary": _summary_value(summary_values, "黄金债市", "黄金", "债券"),
        "risk_note": RISK_NOTE,
        "disclaimer": DISCLAIMER,
    }
    try:
        material["fallback_script"] = build_90_second_script(response, publication_date)
    except ConfigError as exc:
        material["fallback_script"] = ""
        material["fallback_error"] = str(exc)
    return material


def validate_finance_narration(script: str, material: dict[str, object], *, enforce_length: bool = True) -> None:
    if enforce_length:
        _validate_finance_script(script)
    else:
        _validate_finance_script_safety(script)
    normalized = re.sub(r"\s+", "", script)
    if re.search(r"!\[[^]]*]\([^)]*\)|^#{1,6}\s+|^[\-*+]\s+", script, re.MULTILINE):
        raise ConfigError("finance LLM narration contains markdown")
    if not normalized.endswith(("。", "！", "？")):
        raise ConfigError("finance LLM narration must end with a complete Chinese sentence")
    if "不构成" not in script or "投资建议" not in script:
        raise ConfigError("finance LLM narration is missing investment disclaimer")
    if not any(marker in script for marker in ("风险承受能力", "审慎决策", "市场波动")):
        raise ConfigError("finance LLM narration is missing risk warning")
    prohibited = (r"保证收益", r"稳赚", r"无风险", r"必涨", r"满仓", r"梭哈")
    for pattern in prohibited:
        for match in re.finditer(pattern, script):
            prefix = script[max(0, match.start() - 4) : match.start()]
            if re.search(r"(?:不要|不宜|不可|避免|切勿|不能|别)$", prefix):
                continue
            raise ConfigError("finance LLM narration contains prohibited investment language")
    if any(marker in script for marker in ("以下是", "根据素材", "我将", "口播稿如下", "Markdown")):
        raise ConfigError("finance LLM narration contains explanatory boilerplate")
    if re.search(r"[，。！？；：、]{3,}", normalized):
        raise ConfigError("finance LLM narration contains repeated punctuation")
    source_numbers = _finance_material_number_tokens(material)
    llm_numbers = _number_tokens(script)
    extra_numbers = {value for value in llm_numbers - source_numbers if value not in {"90", "300", "600"}}
    if extra_numbers:
        preview = ", ".join(sorted(extra_numbers)[:5])
        raise ConfigError(f"finance LLM narration contains numbers not present in the source material: {preview}")


def _finance_material_number_tokens(material: dict[str, object]) -> set[str]:
    allowed_keys = {
        "fallback_script",
        "publication_date",
        "summary",
        "indices",
        "index_summary",
        "sector_rows",
        "sector_text",
        "sector_summary",
        "keywords",
        "keyword_summary",
        "strategy",
        "strategy_summary",
        "valuation",
        "valuation_summary",
        "cross_asset",
        "cross_asset_summary",
    }
    return _number_tokens_from_value({key: value for key, value in material.items() if key in allowed_keys})


def _number_tokens_from_value(value: object) -> set[str]:
    if isinstance(value, str):
        return _number_tokens(value)
    if isinstance(value, dict):
        tokens: set[str] = set()
        for nested in value.values():
            tokens.update(_number_tokens_from_value(nested))
        return tokens
    if isinstance(value, list | tuple):
        tokens = set()
        for nested in value:
            tokens.update(_number_tokens_from_value(nested))
        return tokens
    return set()


def _number_tokens(value: str) -> set[str]:
    tokens = set(re.findall(r"\d+(?:\.\d+)?%?", value.replace(",", "")))
    normalized = set(tokens)
    for token in tokens:
        suffix = "%" if token.endswith("%") else ""
        core = token.rstrip("%")
        if core.isdigit():
            normalized.add(str(int(core)) + suffix)
    return normalized


def build_90_second_script(response: str, publication_date: str) -> str:
    try:
        return build_daily_markdown_script(response, publication_date)
    except FinanceScriptError as exc:
        raise ConfigError(str(exc)) from exc


def _publication_date_from_path(path: Path) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not match:
        raise ConfigError(f"finance markdown filename must start with YYYY-MM-DD: {path.name}")
    return match.group(1)


@register(
    "finance",
    meta=PipelineMeta(
        content_type="finance",
        description="Markdown parsing -> narrated MPT video -> Douyin/Kuaishou/Tencent publish",
        required_params=[],
        external_tools=["MoneyPrinterTurbo"],
        publish_targets=["douyin", "kuaishou", "tencent"],
    ),
)
def run_finance_pipeline(ctx: PipelineContext) -> None:
    task_id = ctx.task_id
    snapshot = ctx.snapshot
    artifacts = ctx.artifacts
    store = ctx.store
    settings = ctx.settings
    params = FinanceParams.model_validate(ctx.route.params)
    source_dir = params.source_dir or settings.finance_md_dir
    job_dir = store.job_dir(task_id)

    store.mark_running(task_id, PipelineStep.SOURCE_SCAN)
    source = select_daily_markdown(source_dir, params.date)
    publication_date = _publication_date_from_path(source)
    response = extract_response(source.read_text(encoding="utf-8-sig"))
    material = build_finance_script_material(response, publication_date)
    generator = ScriptGenerationService(settings)
    try:
        if params.script_writer == "llm":
            generation = generator.generate(
                content_type="finance",
                material=material,
                fallback_script=str(material.get("fallback_script") or ""),
                failure_policy=params.script_failure_policy,
                repair_attempts=params.script_repair_attempts,
                on_attempt=lambda attempt: record_script_attempt_event(store, task_id, attempt),
            )
        else:
            generation = generator.validate_rule(
                content_type="finance",
                material=material,
                script=str(material.get("fallback_script") or ""),
            )
    except Exception as exc:
        artifacts.upload_result = {
            "script_writer": "llm_failed" if params.script_writer == "llm" else "rule_failed",
            "script_writer_error": str(exc),
        }
        store.set_artifacts(task_id, artifacts)
        store.event(task_id, "script_generation_failed", {"writer": params.script_writer, "error": str(exc)[:500]})
        raise ConfigError(f"finance script generation failed: {exc}") from exc
    script = generation.script
    audit = generation.audit.model_dump(mode="json")
    script_path = job_dir / "finance_script.txt"
    legacy_audit_path = job_dir / "finance_script_audit.json"
    script_path.write_text(script, encoding="utf-8")
    legacy_audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    audit_paths = persist_script_audit(job_dir, generation.audit)
    if generation.audit.plan:
        store.event(
            task_id,
            "script_plan_generated",
            {
                "main_fact_id": generation.audit.plan.main_fact_id,
                "selected_fact_ids": generation.audit.plan.required_facts,
            },
        )
    artifacts.source_document = source
    artifacts.narration_script = script
    artifacts.script_path = script_path
    artifacts.script_generation_audit = audit
    artifacts.script_audit_path = audit_paths["audit"]
    artifacts.script_plan_path = audit_paths["plan"]
    artifacts.script_attempts_path = audit_paths["attempts"]
    artifacts.script_quality_report_path = audit_paths["quality"]
    artifacts.upload_result = {
        "script_writer": generation.audit.generation_mode,
        "script_prompt_version": generation.audit.prompt_version,
        "script_attempts": len(generation.audit.attempts),
        "script_warnings": [issue.message for issue in generation.audit.quality_report.warnings],
    }
    store.set_artifacts(task_id, artifacts)

    title = params.title or f"每日基金日报 · {publication_date}"
    store.mark_running(task_id, PipelineStep.VIDEO)
    mpt_result = call_finance_mpt(
        publication_date=publication_date,
        title=title,
        script=script,
        output_dir=job_dir / "video",
        settings=settings,
        dry_run=params.dry_run,
    )
    artifacts.video = mpt_result.video
    artifacts.subtitle = mpt_result.subtitle
    artifacts.mpt_task_dir = mpt_result.task_dir
    validate_spoken_subtitle(mpt_result.subtitle)
    if not params.dry_run:
        artifacts.validation.video = validate_video(mpt_result.video, expected_aspect="9:16", require_audio=True)
    store.set_artifacts(task_id, artifacts)

    plan = resolve_publish_plan("finance", snapshot.task, settings=settings)
    default_targets = [
        PublishTarget(platform="douyin", account=params.douyin_account),
        PublishTarget(platform="kuaishou", account=params.kuaishou_account),
        PublishTarget(platform="tencent", account=params.tencent_account),
    ]
    final, error = publish_generated_video(
        snapshot=snapshot,
        store=store,
        artifacts=artifacts,
        settings=settings,
        video=mpt_result.video,
        title=title,
        description=params.description,
        tags=params.tags,
        requested=plan["requested"],
        targets=plan["targets"] or default_targets,
        dry_run=params.dry_run,
    )
    store.finish(task_id, final, error)
