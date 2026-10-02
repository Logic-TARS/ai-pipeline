from __future__ import annotations

import re
from datetime import datetime

from content_pipeline.script_generation.models import (
    QualityIssue,
    ScriptFact,
    ScriptPlan,
    ScriptQualityReport,
    StructuredFacts,
)

__all__ = ["count_script_characters", "extract_number_tokens", "validate_script"]

_MARKDOWN_RE = re.compile(r"!\[[^]]*]\([^)]*\)|^#{1,6}\s+|^[\-*+]\s+|```", re.MULTILINE)
_PATH_RE = re.compile(r"(?:^|[：:])(?:~|[A-Za-z]:)?[/\\][^\s，。]+\.(?:md|txt|json|srt)", re.IGNORECASE)
_EXPLANATION_MARKERS = ("以下是", "根据素材", "我将", "口播稿如下", "Markdown")
_STYLE_MARKERS = ("值得注意的是", "不难发现", "可以说", "总的来说", "让我们拭目以待", "赋能千行百业")


def count_script_characters(script: str) -> int:
    return len(re.sub(r"\s+", "", script))


def extract_number_tokens(value: str) -> set[str]:
    tokens = set(re.findall(r"\d+(?:\.\d+)?%?", value.replace(",", "")))
    normalized = set(tokens)
    for token in tokens:
        suffix = "%" if token.endswith("%") else ""
        core = token.rstrip("%")
        if core.isdigit():
            normalized.add(str(int(core)) + suffix)
    return normalized


def validate_script(
    script: str,
    facts: StructuredFacts,
    *,
    plan: ScriptPlan | None = None,
) -> ScriptQualityReport:
    normalized = re.sub(r"\s+", "", script)
    issues: list[QualityIssue] = []
    minimum, maximum = (350, 500) if facts.content_type == "ai_briefing" else (300, 600)
    _require(
        minimum <= len(normalized) <= maximum,
        issues,
        "length",
        f"正文去空白后必须为 {minimum}-{maximum} 字，当前 {len(normalized)} 字",
    )
    _require(not _MARKDOWN_RE.search(script), issues, "markdown", "正文不能包含 Markdown")
    _require(not _PATH_RE.search(script), issues, "file_path", "正文不能包含文件路径")
    _require(
        not any(marker in script for marker in _EXPLANATION_MARKERS),
        issues,
        "explanation_prefix",
        "正文不能包含解释性前缀",
    )
    _require(normalized.endswith(("。", "！", "？")), issues, "sentence_end", "正文必须以完整中文句子结束")
    _require(
        not re.search(r"[，。！？；：、]{3,}", normalized),
        issues,
        "punctuation",
        "正文包含异常连续标点",
    )
    extra_numbers = {
        number
        for number in extract_number_tokens(script)
        if number not in set(facts.source_numbers) and number.rstrip("%") not in set(facts.source_numbers)
    }
    if extra_numbers:
        _issue(
            issues,
            "unsupported_number",
            "正文包含素材外数字",
            evidence=", ".join(sorted(extra_numbers)[:8]),
        )
    selected = _selected_facts(facts, plan)
    for fact in selected:
        if fact.kind not in {"index", "sector", "risk"}:
            _require(
                _fact_matches(script, fact),
                issues,
                "required_fact_missing",
                f"正文未覆盖选中的必选事实：{fact.id}",
                evidence=fact.id,
            )
    if facts.content_type == "ai_briefing":
        _validate_ai(script, selected, issues)
    else:
        _validate_finance(script, selected, issues)
    for marker in _STYLE_MARKERS:
        if marker in script:
            _issue(issues, "style_boilerplate", f"建议删除套话：{marker}", severity="warning", evidence=marker)
    return ScriptQualityReport(
        passed=not any(issue.severity == "error" for issue in issues),
        character_count=len(normalized),
        issues=issues,
        checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def _selected_facts(facts: StructuredFacts, plan: ScriptPlan | None) -> list[ScriptFact]:
    if plan is None:
        return [fact for fact in facts.facts if fact.required]
    selected = set(plan.required_facts) | {plan.main_fact_id}
    return [fact for fact in facts.facts if fact.id in selected]


def _validate_ai(script: str, facts: list[ScriptFact], issues: list[QualityIssue]) -> None:
    for fact in facts:
        if _status_upgraded(script, fact):
            _issue(
                issues,
                "ai_status_upgrade",
                f"正文可能把非确定状态升级为已完成事实：{fact.id}",
                evidence=fact.id,
            )


def _status_upgraded(script: str, fact: ScriptFact) -> bool:
    if not set(fact.status_markers) & {"planned", "possible", "testing"}:
        return False
    anchor = next((entity for entity in fact.entities if len(entity) >= 2 and entity in script), None)
    if not anchor:
        return False
    windows = _anchor_windows(script, anchor, radius=45)
    completed = ("已发布", "已上线", "已确认", "正式发布", "正式上线", "已经推出")
    source_completed = "completed" in fact.status_markers
    return not source_completed and any(any(marker in window for marker in completed) for window in windows)


def _validate_finance(script: str, facts: list[ScriptFact], issues: list[QualityIssue]) -> None:
    _require(
        "不构成" in script and "投资建议" in script,
        issues,
        "finance_disclaimer",
        "财经口播必须包含不构成投资建议声明",
    )
    _require(
        any(marker in script for marker in ("风险承受能力", "审慎决策", "市场波动", "注意风险")),
        issues,
        "finance_risk_warning",
        "财经口播必须包含风险提示",
    )
    for fact in facts:
        if fact.kind in {"index", "sector"}:
            _validate_market_anchor(script, fact, issues)
    prohibited = (
        r"保证收益",
        r"稳赚",
        r"无风险",
        r"必涨",
        r"(?:建议|应该|必须|可以)?满仓(?!位)",
        r"梭哈",
    )
    for pattern in prohibited:
        for match in re.finditer(pattern, script):
            prefix = script[max(0, match.start() - 4) : match.start()]
            if re.search(r"(?:不要|不宜|不可|避免|切勿|不能|别)$", prefix):
                continue
            _issue(issues, "finance_prohibited", "财经口播包含确定性或诱导性投资表述", evidence=match.group())
            break


def _validate_market_anchor(script: str, fact: ScriptFact, issues: list[QualityIssue]) -> None:
    if not fact.subject or fact.subject not in script:
        _issue(
            issues,
            "required_fact_missing",
            f"正文未覆盖选中的具体行情主体：{fact.subject or fact.id}",
            evidence=fact.id,
        )
        return
    if not fact.numbers:
        _issue(
            issues,
            "finance_number_binding",
            f"{fact.subject} 的源事实缺少可校验数值",
            evidence=fact.id,
        )
        return
    clauses = _subject_clauses(script, fact.subject)
    anchored = next((clause for clause in clauses if set(fact.numbers) & extract_number_tokens(clause)), None)
    if anchored is None:
        _issue(
            issues,
            "finance_number_binding",
            f"{fact.subject} 与其数值未在同句或近邻窗口出现",
            evidence=fact.id,
        )
        return
    expected_direction = fact.direction
    actual_direction = _direction(anchored)
    if expected_direction and actual_direction and expected_direction != actual_direction:
        _issue(
            issues,
            "finance_direction_mismatch",
            f"{fact.subject} 的涨跌方向与素材不一致",
            evidence=fact.id,
        )
    subject_context = "".join(_anchor_windows(script, fact.subject, radius=24))
    if fact.unit == "percent" and "百分点" in subject_context:
        _issue(
            issues,
            "finance_unit_mismatch",
            f"{fact.subject} 的百分比被写成百分点",
            evidence=fact.id,
        )
    if fact.unit == "percentage_point" and "百分点" not in anchored:
        _issue(
            issues,
            "finance_unit_mismatch",
            f"{fact.subject} 的百分点单位缺失或被改写",
            evidence=fact.id,
        )
    if fact.unit == "point" and any(number.rstrip("%") in anchored for number in fact.numbers) and "点" not in anchored:
        _issue(issues, "finance_unit_mismatch", f"{fact.subject} 的点位单位缺失", evidence=fact.id)


def _subject_clauses(script: str, subject: str) -> list[str]:
    clauses = []
    for match in re.finditer(re.escape(subject), script):
        previous = max(script.rfind(mark, 0, match.start()) for mark in "。！？；，")
        following = [position for mark in "。！？；，" if (position := script.find(mark, match.end())) >= 0]
        end = min(following) + 1 if following else min(len(script), match.end() + 60)
        clauses.append(script[previous + 1 : end])
    return clauses


def _direction(text: str) -> str | None:
    if re.search(r"(?:下跌|跌|回落|走低)|-\d", text):
        return "down"
    if re.search(r"(?:上涨|涨|走高|上行)|\+\d", text):
        return "up"
    if any(marker in text for marker in ("持平", "平收")):
        return "flat"
    return None


def _anchor_windows(script: str, anchor: str, *, radius: int) -> list[str]:
    windows = []
    for match in re.finditer(re.escape(anchor), script):
        start = max(0, match.start() - radius)
        end = min(len(script), match.end() + radius)
        windows.append(script[start:end])
    return windows


def _fact_matches(script: str, fact: ScriptFact) -> bool:
    entities = [entity for entity in fact.entities if len(entity) >= 2]
    entity_match = not entities or any(entity in script for entity in entities[:5])
    number_match = not fact.numbers or bool(set(fact.numbers) & extract_number_tokens(script))
    return entity_match and number_match


def _require(
    condition: bool,
    issues: list[QualityIssue],
    code: str,
    message: str,
    *,
    evidence: str | None = None,
) -> None:
    if not condition:
        _issue(issues, code, message, evidence=evidence)


def _issue(
    issues: list[QualityIssue],
    code: str,
    message: str,
    *,
    severity: str = "error",
    evidence: str | None = None,
) -> None:
    issues.append(QualityIssue(code=code, message=message, severity=severity, evidence=evidence))
