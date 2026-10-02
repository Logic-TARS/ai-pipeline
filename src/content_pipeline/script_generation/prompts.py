from __future__ import annotations

import json
from typing import Any

from content_pipeline.script_generation.models import ScriptPlan, StructuredFacts

__all__ = [
    "AI_PROMPT_VERSION",
    "DRAFT_PROMPT_VERSION",
    "FINANCE_PROMPT_VERSION",
    "PLAN_PROMPT_VERSION",
    "REPAIR_PROMPT_VERSION",
    "build_draft_prompts",
    "build_plan_prompts",
    "build_repair_prompts",
]

AI_PROMPT_VERSION = "ai-briefing-v3"
FINANCE_PROMPT_VERSION = "finance-v3"
PLAN_PROMPT_VERSION = "script-plan-v3"
DRAFT_PROMPT_VERSION = "script-draft-v3"
REPAIR_PROMPT_VERSION = "script-repair-v3"

_COMMON_SYSTEM = (
    "你是中文短视频口播编辑。只依据提供的结构化事实工作，不虚构经历、身份、采访、因果或数据。"
    "不模仿任何特定作者的人格、口癖或标志性句式。表达自然、准确、克制，避免新闻稿腔、空泛拔高和套话。"
)


def build_plan_prompts(facts: StructuredFacts) -> tuple[str, str]:
    requirements = _requirements(facts.content_type)
    return (
        _COMMON_SYSTEM + "先规划叙事主线，不写成稿。只输出合法 JSON。",
        f"""为 90 秒口播制定写作计划。先从事实包中选择唯一主事实，再安排事实顺序和收束。
{requirements}
JSON 必须包含：mainline、main_fact_id、opening、sections、required_facts、risk_close。
main_fact_id 和 required_facts 只能填写事实包中存在的 id；required=true 的事实必须全部选择。
事实包：
{_facts_json(facts)}""",
    )


def build_draft_prompts(facts: StructuredFacts, plan: ScriptPlan) -> tuple[str, str]:
    requirements = _requirements(facts.content_type)
    return (
        _COMMON_SYSTEM + "按照已确认的主线写最终口播。只输出正文，不输出标题、解释、列表、Markdown 或 JSON。",
        f"""根据计划和事实包写稿。
{requirements}
写作要求：围绕 main_fact_id 展开，并覆盖 required_facts；用自然转场串联事实。
不得新增事实或数字；必须以完整中文句子结束。
计划：
{json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2)}
事实包：
{_facts_json(facts)}""",
    )


def build_repair_prompts(
    facts: StructuredFacts,
    plan: ScriptPlan,
    script: str,
    issues: list[dict[str, Any]],
) -> tuple[str, str]:
    return (
        _COMMON_SYSTEM + "你只修复指出的问题，保持正确事实与整体主线。只输出修复后的完整正文。",
        f"""修复口播稿。不要解释改动，不要引入任何新事实或数字。
问题：
{json.dumps(issues, ensure_ascii=False, indent=2)}
计划：
{json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2)}
事实包：
{_facts_json(facts)}
待修稿：
{script}""",
    )


def _facts_json(facts: StructuredFacts) -> str:
    return json.dumps(facts.model_dump(mode="json"), ensure_ascii=False, indent=2)


def _requirements(content_type: str) -> str:
    if content_type == "ai_briefing":
        return (
            "硬要求：正文去除所有空白后 350-500 字；保留重点事实、关键实体和每条事实的状态边界，"
            "不得把计划、测试、传闻或可能性写成已发布、已上线或已确认。"
        )
    if content_type == "finance":
        return (
            "硬要求：正文去除所有空白后 300-600 字；包含事实包中的指数、板块、方向、数值和单位；"
            "保留风险提示和“不构成投资建议”；不承诺收益，不给确定性买卖建议。"
        )
    return (
        "硬要求：正文去除所有空白后 300-600 字；只覆盖事实包中实际提供的资产模块；"
        "保留风险提示和“不构成投资建议”；不要虚构指数或板块信息。"
    )
