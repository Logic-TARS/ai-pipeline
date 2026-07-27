from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_pipeline.ai_briefing_pipeline import (
    acquire_run_lock,
    build_90_second_briefing_script,
    build_publish_title,
    build_video_title,
    _sau_file_hash,
    normalize_date,
    normalize_handoff,
    release_run_lock,
)
from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


SAMPLE_ARTICLE = """---
标题: 国产模型集中亮相
作者: Wallbreaker
摘要: 世界人工智能大会开幕，国产模型团队集中发布新一代开源模型，编码、长上下文与端侧推理成为竞争焦点。海外方面，芯片厂商继续扩建主权人工智能基础设施，监管机构也要求平台向第三方助手开放更多关键接口。
---

# 国产模型集中亮相

## 今日焦点

### Qwen 新模型发布并开放权重

新模型进一步提升了编码和工具调用能力，并将向开发者开放权重。

### Kimi 登上编码评测榜首

新的混合专家模型在多个前端编码任务中取得领先成绩。

## 前沿动态

### Nvidia 建设新一代 AI 工厂

项目将部署新一代 CPU 和 GPU，服务当地科研和企业。

### 端侧小模型继续提速

多家厂商发布可在消费级设备运行的小模型。

### 欧盟推进平台开放

监管要求大型平台向竞争对手开放关键能力。

## 一句话快讯

- 芯片企业上调年度资本支出
- 企业开始加强智能体身份安全

## 结语

人工智能竞争已经从单一模型能力扩展到基础设施、生态和监管的综合较量。未来的胜负将取决于产品落地与开放生态。
"""


def _make_day(root: Path, date: str = "20260720") -> Path:
    day = root / date
    day.mkdir(parents=True)
    article = day / "article.md"
    text = day / "article.txt"
    article.write_text(SAMPLE_ARTICLE, encoding="utf-8")
    text.write_text("每日AI简报正文。" * 100, encoding="utf-8")
    (day / "video_handoff.json").write_text(
        json.dumps(
            {
                "date": date,
                "title": "国产模型集中亮相",
                "article_path": str(article),
                "text_path": str(text),
                "output_dir": str(day / "video"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return day


def test_normalize_date_never_falls_back() -> None:
    assert normalize_date("2026-07-20") == "20260720"
    with pytest.raises(Exception, match="date must be"):
        normalize_date("yesterday")


def test_builds_clean_90_second_script() -> None:
    script = build_90_second_briefing_script(SAMPLE_ARTICLE, "20260720")
    assert 350 <= len(script) <= 500
    assert "Qwen" in script
    assert "Nvidia" in script
    assert "![" not in script
    assert "article.md" not in script
    assert script.endswith("。")


def test_sau_file_hash_matches_partial_sha256_contract(tmp_path: Path) -> None:
    video = tmp_path / "briefing.mp4"
    video.write_bytes(b"header" + b"x" * (2 * 1024 * 1024) + b"footer")
    assert len(_sau_file_hash(video)) == 64


def test_publish_title_prefers_short_complete_lead() -> None:
    title = "WAIC 2026 开幕即高潮：Qwen 2.4万亿参数开路，Kimi K3封王，国产模型军团全线出击"
    assert build_publish_title(title) == "WAIC 2026 开幕即高潮"
    assert len(build_publish_title("没有标点但是特别特别长的人工智能每日新闻标题示例")) <= 20
    assert build_video_title(title) == "WAIC 2026 开幕即高潮"
    assert len(build_video_title("没有标点但是特别特别长的人工智能每日新闻标题示例")) <= 16


def test_handoff_accepts_legacy_sampo_and_rejects_external_output(tmp_path: Path) -> None:
    day = _make_day(tmp_path)
    handoff_path = day / "video_handoff.json"
    raw = json.loads(handoff_path.read_text(encoding="utf-8"))
    raw["consumer_profile"] = "sampo"
    normalized = normalize_handoff(raw, date="20260720", handoff_path=handoff_path, day_dir=day)
    assert normalized["consumer_profile"] == "sampo"
    assert normalized["runner"] == "ai-popline"
    raw["output_dir"] = str(tmp_path / "outside")
    with pytest.raises(Exception, match="output_dir"):
        normalize_handoff(raw, date="20260720", handoff_path=handoff_path, day_dir=day)


def test_run_lock_rejects_live_process(tmp_path: Path) -> None:
    lock = tmp_path / "handoff.lock.json"
    acquire_run_lock(lock, "20260720")
    try:
        with pytest.raises(Exception, match="already_running"):
            acquire_run_lock(lock, "20260720")
    finally:
        release_run_lock(lock)
    assert not lock.exists()


def test_ai_briefing_dry_run_dual_writes_status_without_legacy_video(tmp_path: Path) -> None:
    source = tmp_path / "briefings"
    day = _make_day(source)
    settings = Settings(
        data_dir=tmp_path / "output",
        ai_briefing_dir=source,
        mpt_dir=tmp_path / "mpt",
    )
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="生成每日 AI 资讯视频",
            content_type="ai_briefing",
            params={"date": "20260720", "handoff_wait_seconds": 0, "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.SUCCEEDED
    assert snapshot.artifacts.narration_script and len(snapshot.artifacts.narration_script) >= 350
    assert snapshot.artifacts.video and snapshot.artifacts.video.is_file()
    assert not (day / "video" / "briefing.mp4").exists()
    external = json.loads((day / "video_status.json").read_text(encoding="utf-8"))
    assert external["status"] == "succeeded"
    assert external["runner"] == "ai-popline"
    assert external["steps"]["publish_douyin"] == "skipped"


def test_publish_targets_are_fixed_and_independent(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "briefings"
    _make_day(source)
    settings = Settings(data_dir=tmp_path / "output", ai_briefing_dir=source, mpt_dir=tmp_path / "mpt")

    used_titles: list[str] = []

    def fake_upload(*, target, title, **kwargs):
        used_titles.append(title)
        if target.platform == "douyin":
            return {"success": True, "visibility": "private"}
        raise RuntimeError("kuaishou failed")

    monkeypatch.setattr("content_pipeline.ai_briefing_pipeline.call_sau_target", fake_upload)
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="生成并发布每日 AI 资讯视频",
            content_type="ai_briefing",
            publish=True,
            params={"date": "20260720", "handoff_wait_seconds": 0, "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.PARTIAL
    assert snapshot.artifacts.publish_results["douyin"]["success"] is True
    assert snapshot.artifacts.publish_results["kuaishou"]["success"] is False
    assert used_titles == ["国产模型集中亮相", "国产模型集中亮相"]
    assert "tencent" not in snapshot.artifacts.publish_results


def test_explicit_tencent_target_adds_draft_and_mixed_delivery(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "briefings"
    _make_day(source)
    settings = Settings(data_dir=tmp_path / "output", ai_briefing_dir=source, mpt_dir=tmp_path / "mpt")

    def fake_upload(*, target, **kwargs):
        if target.platform == "tencent":
            return {"success": True, "delivery_status": "draft", "visibility": "draft"}
        return {"success": True, "visibility": "private"}

    monkeypatch.setattr("content_pipeline.ai_briefing_pipeline.call_sau_target", fake_upload)
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="生成并发布每日 AI 资讯视频",
            content_type="ai_briefing",
            publish=True,
            params={
                "date": "20260720",
                "handoff_wait_seconds": 0,
                "dry_run": True,
                "tencent_account": "破壁人Wallbreaker",
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert set(snapshot.artifacts.publish_results) == {"douyin", "kuaishou", "tencent"}
    assert snapshot.artifacts.upload_result["delivery_states"] == {
        "douyin": "private",
        "kuaishou": "private",
        "tencent": "draft",
    }
    assert snapshot.artifacts.upload_result["visibility"] == "mixed"
