from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .errors import ConfigError
from .job_store import JobStore
from .media_validation import validate_video
from .models import (
    ArtifactSet,
    FinanceParams,
    JobSnapshot,
    JobStatus,
    PipelineStep,
    PublishTarget,
)
from .settings import Settings
from .tools.finance_mpt_client import (
    call_finance_mpt,
    looks_like_file_reference,
    validate_spoken_subtitle,
)
from .tools.sau_client import call_sau_target


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
        if candidates:
            return candidates[0]
    wanted = ", ".join(item.isoformat() for item in dates)
    raise ConfigError(f"no finance markdown found for: {wanted}")


def extract_response(markdown: str) -> str:
    match = re.search(r"(?im)^##\s+Response\s*$", markdown)
    if not match:
        raise ConfigError("finance markdown is missing a '## Response' section")
    response = markdown[match.end():].strip()
    if not response:
        raise ConfigError("finance markdown '## Response' section is empty")
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
            return markdown[heading.end():end].strip()
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
    if not 350 <= len(script) <= 500:
        raise ConfigError(
            "finance narration must contain 350-500 characters; "
            f"generated {len(script)} characters"
        )
    normalized = script.replace(" ", "")
    if (
        looks_like_file_reference(normalized)
        or "文件路径" in script
        or re.search(r"(?:^|[：:])(?:~|[A-Za-z]:)[/\\].+\.(?:md|txt|json|srt)", script, re.IGNORECASE)
    ):
        raise ConfigError("finance narration contains a file reference instead of spoken content")
    if not all(marker in script for marker in ("指数", "板块")):
        raise ConfigError("finance narration is missing required index or sector market information")


def build_90_second_script(response: str, publication_date: str) -> str:
    summary_values = _summary_table(response)
    summary_match = re.search(r"(?m)一句话总结[：:]\s*\*{0,2}\s*(.+)$", response)
    summary = _first_sentence(summary_match.group(1)) if summary_match else _summary_value(
        summary_values, "盘面定性", "顶部摘要", "一句话总结"
    )
    if not summary:
        summary = _trim_complete(_first_sentence(_section(response, "顶部摘要")), 60)

    index_section = _section(response, "四大指数", "四指数行情", "四指数表格")
    index_rows = _table_rows(index_section)[:4]
    indices = []
    for row in index_rows:
        if len(row) >= 3:
            indices.append(f"{row[0]}报{row[1]}点，{row[2]}")
    index_summary = _summary_value(summary_values, "四大指数", "四指数")

    sector_section = _section(response, "板块轮动")
    leaders: list[str] = []
    laggards: list[str] = []
    mode = ""
    for line in sector_section.splitlines():
        cleaned_line = _clean_markdown(line)
        if "领涨" in cleaned_line:
            mode = "up"
            continue
        if "领跌" in cleaned_line:
            mode = "down"
            continue
        if line.lstrip().startswith(("•", "-")):
            phrase = _trim_complete(_clean_markdown(line), 40)
            if mode == "up" and not leaders:
                leaders.append(phrase)
            elif mode == "down" and not laggards:
                laggards.append(phrase)
            continue
        if line.strip().startswith("|") and not re.search(r"\|\s*:?-{2,}", line):
            cells = [_clean_markdown(cell) for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in {"板块", "品种"}:
                phrase = f"{cells[0]}{cells[1]}"
                if mode == "up" and not leaders:
                    leaders.append(phrase)
                elif mode == "down" and not laggards:
                    laggards.append(phrase)
    sector_summary = _summary_value(summary_values, "板块轮动")
    sector_detail = _trim_complete(_clean_markdown(sector_section), 45) if sector_section else ""

    keyword_section = _section(response, "今日关键词", "三个信号", "核心信号")
    keywords = []
    for line in keyword_section.splitlines():
        named_match = re.match(r"\s*\*{0,2}(?:\d+[.、]|[①-⑩])\s*[「“](.+?)[」”]", line)
        numbered_match = re.match(r"\s*\d+[.、]\s*(.+)", line)
        if named_match:
            keywords.append(_clean_markdown(named_match.group(1)))
        elif numbered_match:
            keywords.append(_first_sentence(numbered_match.group(1)))
        if len(keywords) == 3:
            break
    keyword_summary = _summary_value(summary_values, "今日关键词", "三个信号", "核心信号")
    keyword_detail = _trim_complete(_clean_markdown(keyword_section), 45) if keyword_section else ""

    interpretation = _section(response, "我的解读", "策略建议", "投资建议")
    advice_match = re.search(r"(?m)^.*我的建议.*$", interpretation)
    strategy_match = re.search(r"(?im)^\s*\*\*策略上[：:]?\*\*\s*$", interpretation)
    if strategy_match:
        strategy = re.split(
            r"(?m)^\s*(?:\*真正|[-═─]{3,}|📁)", interpretation[strategy_match.end():], maxsplit=1
        )[0]
        strategy_items = [
            _clean_markdown(line)
            for line in strategy.splitlines()
            if line.lstrip().startswith(("•", "-")) and _clean_markdown(line)
        ]
        advice = "；".join(strategy_items[:2]) if strategy_items else _trim_complete(_clean_markdown(strategy), 50)
    else:
        advice = _trim_complete(
            _first_sentence(advice_match.group(0)) if advice_match else _first_sentence(interpretation),
            55,
        )
    advice_summary = _summary_value(summary_values, "我的解读", "策略建议", "投资建议")
    valuation_section = _section(response, "估值水位")
    valuation_rows = _table_rows(valuation_section)[:4]
    valuation_detail = "；".join(
        f"{row[0]}PE{row[1]}，历史百分位{row[2]}，{row[-1]}"
        for row in valuation_rows
        if len(row) >= 4
    )
    valuation_summary = _summary_value(summary_values, "估值水位", "估值") or valuation_detail
    cross_asset_summary = _summary_value(summary_values, "黄金债市", "黄金", "债券") or _trim_complete(
        _clean_markdown(_section(response, "黄金债市", "黄金", "债券")), 100
    )

    date_text = publication_date.replace("-", "年", 1).replace("-", "月", 1) + "日"
    parts = [f"{date_text}A股收盘观察。"]
    if summary:
        parts.append(summary + "。")
    if indices:
        parts.append("四大指数方面，" + "；".join(indices) + "。")
    elif index_summary:
        parts.append("四大指数方面，" + index_summary + "。")
    if leaders or laggards:
        sector_bits = []
        if leaders:
            sector_bits.append("领涨方向是" + leaders[0])
        if laggards:
            sector_bits.append("领跌方向是" + laggards[0])
        parts.append("板块方面，" + "；".join(sector_bits) + "。")
    elif sector_summary:
        parts.append("板块方面，" + sector_summary + "。")
    elif sector_detail:
        parts.append("板块方面，" + sector_detail + "。")
    if advice:
        parts.append(advice + "。")
    elif advice_summary:
        parts.append("策略上，" + advice_summary + "。")
    if keywords:
        parts.append("今天需要关注的信号是：" + "；".join(keywords) + "。")
    elif keyword_summary:
        parts.append("今天需要关注的信号是：" + keyword_summary + "。")
    elif keyword_detail:
        parts.append("今天需要关注的信号是：" + keyword_detail + "。")
    if valuation_summary:
        parts.append("估值方面，" + valuation_summary + "。")
    if cross_asset_summary:
        parts.append("其他资产方面，" + cross_asset_summary + "。")

    core = "".join(parts)
    if len(core) < 330:
        plain_interpretation = _clean_markdown(interpretation)
        for sentence in re.split(r"(?<=[。！？])", plain_interpretation):
            sentence = sentence.strip()
            if sentence and sentence not in core:
                core += sentence
            if len(core) >= 410:
                break

    required_tail = RISK_NOTE + DISCLAIMER
    core_limit = FINANCE_NARRATION_MAX_CHARS - len(required_tail)
    core = re.sub(r"[。！？；]{2,}", "。", core)
    core = _trim_complete(core, core_limit)
    script = core.rstrip("。") + "。" + required_tail
    _validate_finance_script(script)
    return script


def _publication_date_from_path(path: Path) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not match:
        raise ConfigError(f"finance markdown filename must start with YYYY-MM-DD: {path.name}")
    return match.group(1)


def run_finance_pipeline(
    *,
    task_id: str,
    snapshot: JobSnapshot,
    artifacts: ArtifactSet,
    store: JobStore,
    settings: Settings,
) -> None:
    params = FinanceParams.model_validate(snapshot.task.params)
    source_dir = params.source_dir or settings.finance_md_dir
    job_dir = store.job_dir(task_id)

    store.mark_running(task_id, PipelineStep.SOURCE_SCAN)
    source = select_daily_markdown(source_dir, params.date)
    publication_date = _publication_date_from_path(source)
    response = extract_response(source.read_text(encoding="utf-8-sig"))
    script = build_90_second_script(response, publication_date)
    script_path = job_dir / "finance_script.txt"
    script_path.write_text(script, encoding="utf-8")
    artifacts.source_document = source
    artifacts.narration_script = script
    artifacts.script_path = script_path
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

    if not snapshot.task.publish:
        artifacts.upload_result = {"skipped": True, "reason": "publish_not_requested"}
        store.set_artifacts(task_id, artifacts)
        store.event(task_id, "upload_skipped", {"reason": "publish_not_requested"})
        store.finish(task_id, JobStatus.SUCCEEDED)
        return

    targets = snapshot.task.publish_targets or [
        PublishTarget(platform="douyin", account=params.douyin_account),
        PublishTarget(platform="kuaishou", account=params.kuaishou_account),
    ]
    store.mark_running(task_id, PipelineStep.UPLOAD)
    for target in targets:
        if target.platform not in {"douyin", "kuaishou"}:
            artifacts.publish_results[target.platform] = {
                "success": False,
                "error": "finance publishing supports only douyin and kuaishou",
            }
            continue
        try:
            result = call_sau_target(
                target=target,
                video=mpt_result.video,
                title=title,
                desc=params.description,
                tags=params.tags,
                settings=settings,
                dry_run=params.dry_run,
            )
            artifacts.publish_results[target.platform] = result
        except Exception as exc:
            artifacts.publish_results[target.platform] = {"success": False, "error": str(exc)}
        store.set_artifacts(task_id, artifacts)
        store.event(task_id, "publish_target_finished", {
            "platform": target.platform,
            "result": artifacts.publish_results[target.platform],
        })

    artifacts.upload_result = {"targets": artifacts.publish_results, "visibility": "private"}
    store.set_artifacts(task_id, artifacts)
    failures = [name for name, result in artifacts.publish_results.items() if not result.get("success")]
    if failures:
        store.finish(task_id, JobStatus.PARTIAL, "publish_failed: " + ", ".join(failures))
    else:
        store.finish(task_id, JobStatus.SUCCEEDED)
