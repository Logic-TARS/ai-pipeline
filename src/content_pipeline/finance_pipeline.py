from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .errors import ConfigError
from .finance_script import FinanceScriptError, build_daily_markdown_script
from .media_validation import validate_video
from .models import FinanceParams, JobStatus, PipelineStep, PublishTarget
from .pipelines.registry import PipelineContext, PipelineMeta, register
from .tools.finance_mpt_client import call_finance_mpt
from .tools.narrated_mpt_client import looks_like_file_reference, validate_spoken_subtitle
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
    response = markdown[match.end() :].strip()
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
        raise ConfigError(f"finance narration must contain 350-500 characters; generated {len(script)} characters")
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
        description="Markdown parsing -> narrated MPT video -> Douyin/Kuaishou private publish",
        required_params=[],
        external_tools=["MoneyPrinterTurbo"],
        publish_targets=["douyin", "kuaishou"],
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
        store.event(
            task_id,
            "publish_target_finished",
            {
                "platform": target.platform,
                "result": artifacts.publish_results[target.platform],
            },
        )

    artifacts.upload_result = {"targets": artifacts.publish_results, "visibility": "private"}
    store.set_artifacts(task_id, artifacts)
    failures = [name for name, result in artifacts.publish_results.items() if not result.get("success")]
    if failures:
        store.finish(task_id, JobStatus.PARTIAL, "publish_failed: " + ", ".join(failures))
    else:
        store.finish(task_id, JobStatus.SUCCEEDED)
