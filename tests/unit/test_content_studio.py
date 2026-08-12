import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_pipeline.api.app import create_app
from content_pipeline.content_studio.models import ResearchSource
from content_pipeline.content_studio.service import ContentStudioService
from content_pipeline.content_studio.store import ContentDraftStore, DraftConflictError
from content_pipeline.content_studio.ttskill_client import TTSkillClient, TTSkillError
from content_pipeline.settings import Settings


def test_draft_store_uses_revision_conflicts_and_atomic_json(tmp_path: Path) -> None:
    store = ContentDraftStore(tmp_path)
    draft = store.create(
        template_id="finance_90s",
        title="今日金融资讯",
        focus_assets=["东方财富"],
        research=[ResearchSource(source_id="gold", label="黄金行情", skill_id="TTFUND_GOLD_INFO")],
    )
    original_revision = draft.revision
    draft.script = "已编辑"
    saved = store.save(draft, expected_revision=original_revision)

    assert saved.revision == original_revision + 1
    assert store.get(draft.draft_id).script == "已编辑"
    assert not list((tmp_path / "content-drafts").rglob("*.tmp"))
    with pytest.raises(DraftConflictError):
        store.save(draft, expected_revision=original_revision)


def test_ttskill_client_rejects_non_allowlisted_skills(tmp_path: Path) -> None:
    client = TTSkillClient(Settings(data_dir=tmp_path))

    with pytest.raises(TTSkillError, match="read-only"):
        client.invoke("ACCOUNT_HOLDING", {})


def test_content_collection_keeps_partial_results(tmp_path: Path, monkeypatch) -> None:
    service = ContentStudioService(Settings(data_dir=tmp_path, finance_md_dir=tmp_path / "missing-finance"))
    monkeypatch.setattr(service, "_queue_collection", lambda _draft_id: None)
    draft = service.store.create(
        template_id="finance_90s",
        title="今日金融资讯",
        focus_assets=["东方财富"],
        research=service._pending_sources("finance_90s", []),
    )

    def invoke(skill_id: str, _body: dict):
        if skill_id == "TTFUND_STOCK_PRICE_QUERY":
            raise TTSkillError("temporary failure")
        if skill_id == "TTFUND_BOND_MARKET":
            return {"data": {"module_1": [{"updateTime": "2026-08-05", "textSummary": "债市偏强"}]}}
        if skill_id == "TTFUND_MACRO_DATA":
            return {
                "data": {
                    "frequencies": [
                        {
                            "频率": "月频数据",
                            "记录": [
                                {
                                    "日期": "2026-07-01",
                                    "CPI:当月同比(%)": 1.0,
                                    "PPI:当月同比(%)": 4.1,
                                    "PMI(%)": 49.2,
                                    "M2:同比(%)": 8.0,
                                }
                            ],
                        }
                    ]
                }
            }
        return {
            "data": {
                "as_of": "2026-08-05",
                "gold_quotes": {
                    "gold_futures_shfe": {
                        "date": "2026-08-05",
                        "close": 910.4,
                        "change_pct": 2.7,
                        "volume": 295465,
                    },
                    "sge_benchmark": {"date": "2026-08-04", "evening_price": 883.88},
                },
                "risk_indicators": {
                    "vix": {"INDICATOR_VAL": 16.5},
                    "dxy": {"INDICATOR_VAL": 99.87},
                    "exchprice": {"EXCHPRICE": 6.7889},
                },
                "news": {
                    "items": [
                        {
                            "publish_date": "2026-08-05",
                            "summary": "美伊局势持续缓和，霍尔木兹海峡重开预期升温。",
                        }
                    ]
                },
            }
        }

    monkeypatch.setattr(service.client, "invoke", invoke)
    service.collect_now(draft.draft_id)
    collected = service.store.get(draft.draft_id)
    service.shutdown()

    assert collected.status == "partial"
    assert {source.source_id for source in collected.research} == {"gold", "bond", "macro-cn", "stock-1"}
    assert sum(source.status == "succeeded" for source in collected.research) == 3
    assert sum(source.status == "failed" for source in collected.research) == 1
    assert collected.research_error
    assert 380 <= len(collected.script) <= 430
    assert "黄金期货主力收于910.4元每克" in collected.script
    assert "涨跌幅2.7%" in collected.script
    assert "PMI49.2%" in collected.script
    assert "VIX为16.5" in collected.script
    assert collected.script.endswith("不构成投资建议。")
    assert "资料不完整时" not in collected.script


def test_content_collection_rejects_single_source_finance_draft(tmp_path: Path, monkeypatch) -> None:
    service = ContentStudioService(Settings(data_dir=tmp_path, finance_md_dir=tmp_path / "missing-finance"))
    monkeypatch.setattr(service, "_queue_collection", lambda _draft_id: None)
    draft = service.store.create(
        template_id="finance_90s",
        title="今日金融资讯",
        focus_assets=[],
        research=service._pending_sources("finance_90s", []),
    )

    def invoke(skill_id: str, _body: dict):
        if skill_id == "TTFUND_BOND_MARKET":
            return {"data": {"module_1": [{"updateTime": "2026-08-05", "textSummary": "债市偏强"}]}}
        raise TTSkillError("temporary failure")

    monkeypatch.setattr(service.client, "invoke", invoke)
    service.collect_now(draft.draft_id)
    collected = service.store.get(draft.draft_id)
    service.shutdown()

    assert collected.status == "failed"
    assert sum(source.status == "succeeded" for source in collected.research) == 1
    assert collected.script == ""
    assert "缺少关键模块" in (collected.research_error or "")


def test_content_collection_does_not_generate_script_when_all_sources_fail(tmp_path: Path, monkeypatch) -> None:
    service = ContentStudioService(Settings(data_dir=tmp_path, finance_md_dir=tmp_path / "missing-finance"))
    monkeypatch.setattr(service, "_queue_collection", lambda _draft_id: None)
    draft = service.store.create(
        template_id="finance_90s",
        title="今日金融资讯",
        focus_assets=[],
        research=service._pending_sources("finance_90s", []),
    )

    monkeypatch.setattr(
        service.client,
        "invoke",
        lambda _skill_id, _body: (_ for _ in ()).throw(TTSkillError("temporary failure")),
    )
    service.collect_now(draft.draft_id)
    collected = service.store.get(draft.draft_id)
    service.shutdown()

    assert collected.status == "failed"
    assert collected.script == ""
    assert collected.research_error == "未能获取任何最新资料，请检查 ttskill 登录和网络状态。"


def test_ai_briefing_template_imports_latest_dated_article(tmp_path: Path) -> None:
    source_root = tmp_path / "briefings"
    older = source_root / "20260804"
    latest = source_root / "20260805"
    older.mkdir(parents=True)
    latest.mkdir()
    (older / "article.md").write_text("---\n标题: 旧简报\n---\n\n旧内容", encoding="utf-8")
    long_summary = "模型发布、算力建设、应用落地与监管规则同步推进，所有事实仍需按来源日期人工核对。" * 10
    (latest / "article.md").write_text(
        f"---\n标题: 最新 AI 简报\n摘要: {long_summary}\n---\n\n# 最新 AI 简报\n\n正文。",
        encoding="utf-8",
    )
    (latest / "video_handoff.json").write_text(
        '{"title":"最新 AI 简报","created_at":"2026-08-05T09:00:00"}', encoding="utf-8"
    )
    service = ContentStudioService(Settings(data_dir=tmp_path / "output", ai_briefing_dir=source_root))
    draft = service.store.create(
        template_id="ai_briefing_90s",
        title="每日 AI 简报",
        focus_assets=[],
        research=service._pending_sources("ai_briefing_90s", []),
    )

    service.collect_now(draft.draft_id)
    collected = service.store.get(draft.draft_id)
    service.shutdown()

    assert collected.status == "ready"
    assert collected.research[0].data_as_of == "20260805"
    assert collected.research[0].payload["title"] == "最新 AI 简报"
    assert "模型发布、算力建设" in collected.research[0].payload["article_markdown"]
    assert 350 <= len(collected.script) <= 500
    assert collected.title == "最新 AI 简报"


def test_finance_template_prefers_today_markdown_before_realtime_sources(tmp_path: Path, monkeypatch) -> None:
    today = datetime.now().date().isoformat()
    source_root = tmp_path / "fund-daily"
    source_root.mkdir()
    (source_root / f"{today}_18-00-00.md").write_text(
        """
## Prompt
不要读这里

## Response
一句话总结：科技成长放量走强，红利防御回落，资金风险偏好修复。

## 四指数表格
| 指数 | 点位 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3832.26 | +0.72% |
| 沪深300 | 4588.20 | +0.85% |
| 创业板指 | 3343.96 | +3.06% |
| 科创50 | 1635.96 | +2.99% |

## 今日板块轮动
领涨方向：
- 传媒 +6.00%，计算机 +5.56%，通信 +4.26%。
领跌方向：
- 银行 -1.38%，食品饮料 -0.55%。

## 今日关键词
1. 高低切换：红利退场，科技接力。
2. AI算力链全线点火。
3. 量能放大，反弹有底气。

## 我的解读
策略上：
- 已上科技车的，持有但不追高。
- 空仓观望的，等回踩和缩量企稳。
""",
        encoding="utf-8",
    )
    service = ContentStudioService(Settings(data_dir=tmp_path / "output", finance_md_dir=source_root))
    monkeypatch.setattr(service, "_queue_collection", lambda _draft_id: None)
    monkeypatch.setattr(
        service.client,
        "invoke",
        lambda _skill_id, _body: (_ for _ in ()).throw(AssertionError("ttskill should not run")),
    )
    draft = service.store.create(
        template_id="finance_90s",
        title="今日金融资讯",
        focus_assets=[],
        research=service._pending_sources("finance_90s", []),
    )

    service.collect_now(draft.draft_id)
    collected = service.store.get(draft.draft_id)
    service.shutdown()

    assert collected.status == "ready"
    assert [source.source_id for source in collected.research] == ["finance-daily"]
    assert 380 <= len(collected.script) <= 430
    assert "上证指数报3832.26点" in collected.script
    assert "板块方面" in collected.script
    assert "今天需要关注的信号" in collected.script
    assert "不要读这里" not in collected.script


def test_content_api_creates_draft_and_queues_dry_run_video(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ContentStudioService, "_queue_collection", lambda _service, _draft_id: None)
    settings = Settings(
        data_dir=tmp_path / "output",
        mpt_dir=tmp_path / "mpt",
        web_allowed_hosts="testserver",
        web_allowed_origins="http://testserver",
        web_auth_required=True,
        web_admin_token="admin-" + "a" * 32,
        web_api_token="api-" + "b" * 32,
        web_session_secret="session-" + "c" * 32,
    )
    app = create_app(settings)
    headers = {"Authorization": "Bearer " + "api-" + "b" * 32}
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        assert client.get("/content/bootstrap").status_code == 401
        content_bootstrap = client.get("/content/bootstrap", headers=headers)
        assert {item["template_id"] for item in content_bootstrap.json()["templates"]} == {
            "finance_90s",
            "ai_briefing_90s",
        }
        template_descriptions = {
            item["template_id"]: item["description"] for item in content_bootstrap.json()["templates"]
        }
        assert "自动生成可审阅" in template_descriptions["finance_90s"]
        assert "自动生成可审阅" in template_descriptions["ai_briefing_90s"]
        created = client.post(
            "/content/drafts",
            headers=headers,
            json={"template_id": "finance_90s", "title": "今日金融资讯", "focus_assets": []},
        )
        draft = created.json()

        def mark_ready(current) -> None:
            current.status = "ready"
            current.research[0].status = "succeeded"

        ready = app.state.content_studio.store.mutate(draft["draft_id"], mark_ready)
        script = ("市场数据需要核对来源日期和统计口径，短期变化不能直接外推为长期趋势。" * 10)[:360]
        script += "以上内容仅为市场信息整理，不构成投资建议。"
        saved = client.patch(
            f"/content/drafts/{draft['draft_id']}",
            headers=headers,
            json={"revision": ready.revision, "title": "今日金融资讯", "script": script},
        )
        generated = client.post(
            f"/content/drafts/{draft['draft_id']}/video",
            headers=headers,
            json={"revision": saved.json()["revision"], "dry_run": True},
        )
        task_id = generated.json()["task_id"]
        for _ in range(30):
            snapshot = client.get(f"/status/{task_id}", headers=headers).json()
            if snapshot["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)

    assert created.status_code == 202
    assert saved.status_code == 200
    assert generated.status_code == 202
    assert snapshot["status"] == "succeeded"
    assert snapshot["task"]["content_type"] == "script_video"


def test_content_video_generation_collects_finance_sources_when_markdown_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(ContentStudioService, "_queue_collection", lambda _service, _draft_id: None)
    settings = Settings(
        data_dir=tmp_path / "output",
        mpt_dir=tmp_path / "mpt",
        finance_md_dir=tmp_path / "missing-finance",
        web_allowed_hosts="testserver",
        web_allowed_origins="http://testserver",
        web_auth_required=True,
        web_admin_token="admin-" + "a" * 32,
        web_api_token="api-" + "b" * 32,
        web_session_secret="session-" + "c" * 32,
    )
    app = create_app(settings)
    app.state.orchestrator.run = lambda _task_id: None
    headers = {"Authorization": "Bearer " + "api-" + "b" * 32}

    def invoke(skill_id: str, _body: dict):
        if skill_id == "TTFUND_BOND_MARKET":
            return {"data": {"module_1": [{"updateTime": "2026-08-05", "textSummary": "债市偏强"}]}}
        if skill_id == "TTFUND_MACRO_DATA":
            return {
                "data": {
                    "frequencies": [
                        {
                            "频率": "月频数据",
                            "记录": [
                                {
                                    "日期": "2026-07-01",
                                    "CPI:当月同比(%)": 1.0,
                                    "PPI:当月同比(%)": 4.1,
                                    "PMI(%)": 49.2,
                                    "M2:同比(%)": 8.0,
                                }
                            ],
                        }
                    ]
                }
            }
        return {
            "data": {
                "as_of": "2026-08-05",
                "gold_quotes": {
                    "gold_futures_shfe": {"date": "2026-08-05", "close": 910.4, "change_pct": 2.7, "volume": 295465},
                    "sge_benchmark": {"date": "2026-08-04", "evening_price": 883.88},
                },
                "risk_indicators": {
                    "vix": {"INDICATOR_VAL": 16.5},
                    "dxy": {"INDICATOR_VAL": 99.87},
                    "exchprice": {"EXCHPRICE": 6.7889},
                },
                "news": {"items": [{"publish_date": "2026-08-05", "summary": "美伊局势持续缓和。"}]},
            }
        }

    monkeypatch.setattr(app.state.content_studio.client, "invoke", invoke)
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        created = client.post(
            "/content/drafts",
            headers=headers,
            json={"template_id": "finance_90s", "title": "今日金融资讯", "focus_assets": []},
        )
        draft = created.json()
        generated = client.post(
            f"/content/drafts/{draft['draft_id']}/video",
            headers=headers,
            json={"revision": draft["revision"], "dry_run": True},
        )
        task_id = generated.json()["task_id"]
        status = client.get(f"/status/{task_id}", headers=headers).json()
        collected = client.get(f"/content/drafts/{draft['draft_id']}", headers=headers).json()

    assert created.status_code == 202
    assert generated.status_code == 202
    assert status["task"]["content_type"] == "script_video"
    assert 380 <= len(status["task"]["params"]["script"]) <= 430
    assert "黄金期货主力收于910.4元每克" in status["task"]["params"]["script"]
    assert collected["status"] == "ready"
    assert {source["source_id"] for source in collected["research"]} == {"gold", "bond", "macro-cn"}
    assert {source["source_id"] for source in collected["research"] if source["status"] == "succeeded"} == {
        "gold",
        "bond",
        "macro-cn",
    }


def test_content_api_deletes_single_and_multiple_drafts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ContentStudioService, "_queue_collection", lambda _service, _draft_id: None)
    settings = Settings(
        data_dir=tmp_path / "output",
        web_allowed_hosts="testserver",
        web_allowed_origins="http://testserver",
        web_auth_required=True,
        web_admin_token="admin-" + "a" * 32,
        web_api_token="api-" + "b" * 32,
        web_session_secret="session-" + "c" * 32,
    )
    app = create_app(settings)
    headers = {"Authorization": "Bearer " + "api-" + "b" * 32}
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        first = client.post(
            "/content/drafts",
            headers=headers,
            json={"template_id": "finance_90s", "title": "第一份", "focus_assets": []},
        ).json()
        second = client.post(
            "/content/drafts",
            headers=headers,
            json={"template_id": "finance_90s", "title": "第二份", "focus_assets": []},
        ).json()
        third = client.post(
            "/content/drafts",
            headers=headers,
            json={"template_id": "finance_90s", "title": "第三份", "focus_assets": []},
        ).json()
        for draft_id in (first["draft_id"], second["draft_id"], third["draft_id"]):
            app.state.content_studio.store.mutate(draft_id, lambda draft: setattr(draft, "status", "failed"))

        deleted = client.delete(f"/content/drafts/{first['draft_id']}", headers=headers)
        missing = client.get(f"/content/drafts/{first['draft_id']}", headers=headers)
        batch = client.post(
            "/content/drafts/batch-delete",
            headers=headers,
            json={"draft_ids": [second["draft_id"], third["draft_id"], first["draft_id"]]},
        )
        listed = client.get("/content/drafts", headers=headers).json()["drafts"]

    assert deleted.status_code == 200
    assert deleted.json() == {"draft_id": first["draft_id"], "deleted": True}
    assert missing.status_code == 404
    assert batch.status_code == 200
    assert set(batch.json()["deleted"]) == {second["draft_id"], third["draft_id"]}
    assert batch.json()["not_found"] == [first["draft_id"]]
    assert {draft["draft_id"] for draft in listed}.isdisjoint(
        {first["draft_id"], second["draft_id"], third["draft_id"]}
    )



def test_content_api_blocks_deleting_collecting_drafts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ContentStudioService, "_queue_collection", lambda _service, _draft_id: None)
    settings = Settings(
        data_dir=tmp_path / "output",
        web_allowed_hosts="testserver",
        web_allowed_origins="http://testserver",
        web_auth_required=True,
        web_admin_token="admin-" + "a" * 32,
        web_api_token="api-" + "b" * 32,
        web_session_secret="session-" + "c" * 32,
    )
    app = create_app(settings)
    headers = {"Authorization": "Bearer " + "api-" + "b" * 32}
    with TestClient(app, base_url="http://testserver", client=("127.0.0.1", 50000)) as client:
        draft = client.post(
            "/content/drafts",
            headers=headers,
            json={"template_id": "finance_90s", "title": "采集中", "focus_assets": []},
        ).json()
        single = client.delete(f"/content/drafts/{draft['draft_id']}", headers=headers)
        batch = client.post(
            "/content/drafts/batch-delete",
            headers=headers,
            json={"draft_ids": [draft["draft_id"]]},
        )

    assert single.status_code == 409
    assert batch.status_code == 200
    assert batch.json()["blocked"] == [draft["draft_id"]]
    assert app.state.content_studio.store.get(draft["draft_id"]).status == "collecting"
