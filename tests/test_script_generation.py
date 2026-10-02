from __future__ import annotations

import json

import pytest

from content_pipeline.script_generation.client import OpenAICompatibleScriptClient
from content_pipeline.script_generation.models import ScriptPlan
from content_pipeline.script_generation.prompts import build_draft_prompts, build_plan_prompts
from content_pipeline.script_generation.quality import validate_script
from content_pipeline.script_generation.service import ScriptGenerationService, build_structured_facts, validate_plan
from content_pipeline.settings import Settings
from content_pipeline.tools import briefing_script_writer

AI_MATERIAL = {
    "date": "20260720",
    "date_text": "2026年7月20日",
    "title": "国产模型集中亮相",
    "summary": "国产模型团队发布开源模型，编码和工具调用成为焦点。",
    "focus_titles": ["Qwen发布新模型", "Kimi编码评测领先"],
    "focus_sentences": ["Qwen发布新模型并开放权重。", "Kimi在多个前端编码任务中取得领先。"],
    "frontier_titles": ["Nvidia建设AI工厂"],
    "frontier_sentences": ["Nvidia将部署CPU和GPU服务科研与企业。"],
    "quick_items": ["端侧小模型继续提速"],
    "fallback_script": "",
}


def _ai_script() -> str:
    script = (
        "2026年7月20日每日AI简报，今天的主线是国产模型集中亮相。Qwen发布新模型并开放权重，"
        "编码和工具调用能力继续提升，开发者生态有望扩大。Kimi在多个前端编码任务中取得领先，"
        "模型竞争正从参数规模转向真实生产力。海外方面，Nvidia将建设AI工厂，部署CPU和GPU服务科研与企业。"
        "端侧小模型也在提速，厂商继续把能力推向消费设备。整体看，模型能力、算力供给和产品落地正在同步推进。"
        "今天的重点不只是单次发布，而是开源生态和工具调用能否稳定进入生产流程。开发者还要继续观察权重开放后的"
        "部署成本、运行稳定性和社区反馈，企业则需要核对实际交付能力。接下来，谁能把模型能力稳定转化为产品体验，"
        "谁就更可能在这一轮竞争中占据主动。"
    )
    return script + (
        "这些变化仍需结合后续测试和实际应用效果持续观察，不能只看发布当天的热度。"
        "对于普通用户，真正有价值的是能力能否稳定、低成本地进入日常工作，而不是宣传中的单项成绩。"
    )


class FakeClient:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)
        self.calls: list[str] = []

    def complete(self, *, label: str, **_kwargs) -> str:
        self.calls.append(label)
        return next(self.responses)


def test_service_runs_plan_draft_and_targeted_repair() -> None:
    plan = json.dumps(
        {
            "mainline": "国产模型竞争转向生产力",
            "main_fact_id": "ai.summary",
            "opening": "日期和主线",
            "sections": ["国产模型", "海外算力", "落地观察"],
            "required_facts": ["ai.summary", "ai.focus.1", "ai.focus.2"],
            "risk_close": None,
        },
        ensure_ascii=False,
    )
    client = FakeClient([plan, "短稿。", _ai_script()])
    result = ScriptGenerationService(Settings(_env_file=None), client=client).generate(
        content_type="ai_briefing",
        material=AI_MATERIAL,
        fallback_script=None,
        repair_attempts=1,
    )

    assert result.audit.generation_mode == "llm_repaired"
    assert [attempt.stage for attempt in result.audit.attempts] == ["plan", "draft", "repair"]
    assert result.audit.quality_report.passed is True
    assert client.calls == ["ai_briefing script plan", "ai_briefing script draft", "ai_briefing script repair"]


def test_service_uses_only_validated_rule_fallback() -> None:
    material = {**AI_MATERIAL, "fallback_script": _ai_script()}
    result = ScriptGenerationService(Settings(_env_file=None), client=FakeClient(["not-json"])).generate(
        content_type="ai_briefing",
        material=material,
        fallback_script=_ai_script(),
        failure_policy="validated_rule_fallback",
    )
    assert result.audit.generation_mode == "validated_rule_fallback"
    assert result.audit.fallback_reason

    with pytest.raises(Exception, match="script generation failed"):
        ScriptGenerationService(Settings(_env_file=None), client=FakeClient(["not-json"])).generate(
            content_type="ai_briefing",
            material=material,
            fallback_script="短稿。",
            failure_policy="validated_rule_fallback",
        )


def test_finance_quality_allows_negated_full_position_but_blocks_advice() -> None:
    material = {
        "publication_date": "2026-07-16",
        "summary": "指数回落，板块分化。",
        "indices": [["上证指数", "3882.41", "-1.85%"]],
        "sector_rows": [["院线", "+6.42%"]],
        "risk_note": "面对市场波动，请结合风险承受能力审慎决策。",
        "disclaimer": "不构成投资建议。",
    }
    facts = build_structured_facts("finance", material)
    base = (
        "2026年7月16日市场观察。指数方面，上证指数报3882.41点，下跌1.85%，市场短线承压。"
        "板块方面，院线上涨6.42%，资金在防御与成长方向之间切换。不要满仓追涨，更不能把单日行情外推成长期趋势。"
        "后续需要观察成交变化、板块持续性和指数承接力度，并结合个人期限与仓位安排做判断。"
        "面对市场波动，请结合自身风险承受能力审慎决策。以上内容仅为市场信息整理，不构成投资建议。"
    )
    script = base + "短期波动可能反复，任何操作都应建立在独立核对数据和理解风险的基础上。" * 3
    report = validate_script(script, facts)
    assert all(issue.code != "finance_prohibited" for issue in report.issues)

    blocked = validate_script(script.replace("不要满仓", "建议满仓"), facts)
    assert any(issue.code == "finance_prohibited" for issue in blocked.issues)


def test_plan_rejects_unknown_and_missing_required_fact_ids() -> None:
    facts = build_structured_facts("ai_briefing", AI_MATERIAL)
    valid = ScriptPlan(
        mainline="国产模型竞争",
        main_fact_id="ai.summary",
        opening="直接开场",
        sections=["焦点", "影响"],
        required_facts=["ai.summary", "ai.focus.1", "ai.focus.2"],
    )
    validate_plan(valid, facts)

    with pytest.raises(Exception, match="unknown fact ids"):
        validate_plan(valid.model_copy(update={"required_facts": [*valid.required_facts, "ai.unknown"]}), facts)
    with pytest.raises(Exception, match="omitted required fact ids"):
        validate_plan(valid.model_copy(update={"required_facts": ["ai.summary"]}), facts)


def test_prompts_and_number_allowlist_exclude_fallback_material() -> None:
    marker = "规则兜底秘密文本98765"
    material = {**AI_MATERIAL, "fallback_script": marker, "fallback_error": "private failure 54321"}
    facts = build_structured_facts("ai_briefing", material)
    plan = ScriptPlan(
        mainline="国产模型竞争",
        main_fact_id="ai.summary",
        opening="直接开场",
        sections=["焦点", "影响"],
        required_facts=["ai.summary", "ai.focus.1", "ai.focus.2"],
    )
    plan_prompt = build_plan_prompts(facts)[1]
    draft_prompt = build_draft_prompts(facts, plan)[1]

    assert marker not in plan_prompt
    assert marker not in draft_prompt
    assert "98765" not in facts.source_numbers
    assert "54321" not in facts.source_numbers


def test_finance_anchor_detects_direction_subject_and_unit_mismatches() -> None:
    material = {
        "summary": "指数回落，板块分化。",
        "indices": [["上证指数", "3882.41", "-1.85%"], ["沪深300", "4698.43", "+0.25%"]],
        "sector_rows": [["院线", "+6.42%"], ["半导体", "-7.87%"]],
        "risk_note": "面对市场波动，请结合风险承受能力审慎决策。",
        "disclaimer": "不构成投资建议。",
    }
    facts = build_structured_facts("finance", material)
    filler = "短期波动不能外推为长期趋势，后续还需观察成交、承接和持续性。" * 4
    wrong = (
        "指数方面，上证指数报4698.43点，上涨1.85%；沪深300报3882.41点，下跌0.25%。"
        "板块方面，院线下跌6.42个百分点，半导体上涨7.87%。"
        + filler
        + "面对市场波动，请结合自身风险承受能力审慎决策。以上内容不构成投资建议。"
    )
    report = validate_script(wrong, facts)
    codes = {issue.code for issue in report.issues}
    assert "finance_number_binding" in codes or "finance_direction_mismatch" in codes
    assert "finance_unit_mismatch" in codes

    valid = wrong.replace("上证指数报4698.43点，上涨1.85%", "上证指数报3882.41点，下跌1.85%")
    valid = valid.replace("沪深300报3882.41点，下跌0.25%", "沪深300报4698.43点，上涨0.25%")
    valid = valid.replace("院线下跌6.42个百分点", "院线上涨6.42%")
    valid = valid.replace("半导体上涨7.87%", "半导体下跌7.87%")
    valid_codes = {issue.code for issue in validate_script(valid, facts).issues}
    assert not {"finance_number_binding", "finance_direction_mismatch", "finance_unit_mismatch"} & valid_codes


def test_ai_status_upgrade_is_detected_per_fact() -> None:
    material = {
        **AI_MATERIAL,
        "focus_sentences": ["Qwen计划下月发布新模型。", "Kimi正在测试新的编码能力。"],
    }
    facts = build_structured_facts("ai_briefing", material)
    script = _ai_script().replace("Qwen发布新模型", "Qwen已发布新模型").replace("Kimi在", "Kimi已上线并在")
    report = validate_script(script, facts)
    assert any(issue.code == "ai_status_upgrade" for issue in report.issues)


def test_failed_quality_does_not_append_duplicate_draft_error_attempt() -> None:
    plan = json.dumps(
        {
            "mainline": "国产模型竞争",
            "main_fact_id": "ai.summary",
            "opening": "日期和主线",
            "sections": ["焦点", "影响"],
            "required_facts": ["ai.summary", "ai.focus.1", "ai.focus.2"],
            "risk_close": None,
        },
        ensure_ascii=False,
    )
    attempts = []
    service = ScriptGenerationService(Settings(_env_file=None), client=FakeClient([plan, "短稿。"]))
    with pytest.raises(Exception, match="script generation failed"):
        service.generate(
            content_type="ai_briefing",
            material=AI_MATERIAL,
            fallback_script=None,
            repair_attempts=0,
            on_attempt=attempts.append,
        )
    assert [attempt.stage for attempt in attempts] == ["plan", "draft"]
    assert attempts[-1].error is None
    assert attempts[-1].quality_report and not attempts[-1].quality_report.passed


def test_openai_client_uses_script_settings_and_router_fallback(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["auth"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAICompatibleScriptClient(
        Settings(
            _env_file=None,
            script_llm_base_url="https://script.example/v1",
            script_llm_api_key="script-key",
            script_llm_model="script-model",
            router_llm_base_url="https://router.example/v1",
            router_llm_model="router-model",
        ),
        timeout=9,
    )
    assert client.complete(system_prompt="system", user_prompt="user") == "ok"
    assert captured["url"] == "https://script.example/v1/chat/completions"
    assert captured["body"]["model"] == "script-model"
    assert captured["auth"] == "Bearer script-key"
    assert captured["timeout"] == 9


def test_openai_client_uses_configured_timeout_by_default(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(_request, timeout):
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    settings = Settings(
        _env_file=None,
        script_llm_base_url="https://script.example/v1",
        script_llm_model="model",
        script_llm_timeout_seconds=37,
    )
    OpenAICompatibleScriptClient(settings).complete(system_prompt="system", user_prompt="user")
    assert captured["timeout"] == 37
    with pytest.raises(ValueError):
        Settings(_env_file=None, script_llm_timeout_seconds=4)
    with pytest.raises(ValueError):
        Settings(_env_file=None, script_llm_timeout_seconds=601)


def test_legacy_briefing_writer_exports_remain_compatible() -> None:
    assert briefing_script_writer.__all__ == [
        "FINANCE_PROMPT_VERSION",
        "PROMPT_VERSION",
        "rewrite_ai_briefing_script_with_llm",
        "rewrite_finance_script_with_llm",
    ]
    assert briefing_script_writer.PROMPT_VERSION
    assert briefing_script_writer.FINANCE_PROMPT_VERSION
