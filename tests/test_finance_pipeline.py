from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from content_pipeline.errors import ConfigError
from content_pipeline.finance_pipeline import (
    build_90_second_script,
    extract_response,
    select_daily_markdown,
)
from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings
from content_pipeline.tools.finance_mpt_client import call_finance_mpt

SAMPLE_MD = """# Cron Job: 每日基金日报

## Prompt

运行 ttskill invoke，不要把这里读成旁白。

## Response

## 🎲 A股收盘简报 · 2026年7月16日

**一句话总结：** 四大指数全线下跌，半导体产业链承压，传媒影视逆势走强。

### 📊 四大指数收盘

| 指数 | 点位 | 涨跌幅 |
|:--|:--:|:--:|
| 上证指数 | 3,882.41 | -1.85% |
| 沪深300 | 4,698.43 | -1.84% |
| 创业板指 | 3,692.46 | -2.95% |
| 科创50 | 1,846.88 | -4.02% |

### 🔄 今日板块轮动

**领涨：**
| 板块 | 涨幅 |
|:--|:--:|
| 院线 | +6.42% |

**领跌：**
| 板块 | 跌幅 |
|:--|:--:|
| 集成电路封测 | -7.87% |

### 🎯 今日关键词

1. **传媒走强** — 暑期档预期升温。
2. **半导体回调** — 高位方向集中获利回吐。
3. **放量下跌** — 后续仍需观察承接力度。

### 🃏 我的解读

今天的下跌更像结构性调整。高估值仓位需要重新评估，不要追涨杀跌。市场波动加大时，应结合自己的风险承受能力控制仓位。我的建议：保持节奏，等待更清晰的确认信号。
"""


SUMMARY_TABLE_MD = """# Cron Job: 每日基金日报

## Response

📄 **2026-07-20 收盘简报已保存到本地**

**文件路径：** `~/hermes/sajin-daily-reports/2026-07-20-a-share-closing-brief.md`

| 模块 | 要点 |
|:----|:------|
| 盘面定性 | 低开高走全线收红，沪深300领涨+1.53%，风格切换明显 |
| 四指数 | 全部收涨：上证+0.85%、沪深300+1.53%、创业板+0.42%、科创50+0.19% |
| 板块轮动 | 资金从电子(-4.81%)抽身，涌入公用事业(+3.83%)、食品饮料(+3.82%)、非银金融(+2.82%)、银行(+2.32%) |
| 估值水位 | 上证和沪深300偏高、创业板中等偏高、科创50极度偏高(98.27%百分位) |
| 黄金债市 | Au99.99报873元/克+0.06%，央行持续增持；债市整体偏弱，信用债较强 |
| 三个信号 | 风格切换、权重归来 / 电子板块高位分化 / 高股息策略再起 |
| 策略建议 | 低位可试探沪深300和银行ETF；电子高位止盈；科创50谨慎持仓 |
"""


def test_selects_today_then_yesterday_and_latest(tmp_path: Path) -> None:
    older = tmp_path / "2026-07-17_10-00-00.md"
    latest = tmp_path / "2026-07-17_18-00-00.md"
    yesterday = tmp_path / "2026-07-16_18-00-00.md"
    for path in (older, latest, yesterday):
        path.write_text(SAMPLE_MD, encoding="utf-8")
    older.touch()
    latest.touch()
    assert select_daily_markdown(tmp_path, today=date(2026, 7, 17)) == latest
    older.unlink()
    latest.unlink()
    assert select_daily_markdown(tmp_path, today=date(2026, 7, 17)) == yesterday


def test_extracts_response_and_builds_short_script() -> None:
    response = extract_response(SAMPLE_MD)
    assert "ttskill invoke" not in response
    script = build_90_second_script(response, "2026-07-16")
    assert 350 <= len(script) <= 500
    assert "上证指数" in script
    assert "院线" in script
    assert "集成电路封测" in script
    assert "风险承受能力" in script
    assert script.endswith("不构成任何投资建议。")


def test_builds_script_from_level_two_headings() -> None:
    response = extract_response(SAMPLE_MD.replace("### ", "## "))
    script = build_90_second_script(response, "2026-07-16")
    assert 350 <= len(script) <= 500
    assert "上证指数" in script
    assert "院线" in script
    assert "风险承受能力" in script


def test_builds_script_from_bold_pseudo_headings() -> None:
    markdown = re.sub(r"(?m)^###\s+(.+)$", r"**\1**", SAMPLE_MD)
    script = build_90_second_script(extract_response(markdown), "2026-07-16")
    assert 350 <= len(script) <= 500
    assert "上证指数" in script
    assert "集成电路封测" in script
    assert "风险承受能力" in script


def test_builds_script_from_summary_table_without_path_leakage() -> None:
    response = extract_response(SUMMARY_TABLE_MD)
    script = build_90_second_script(response, "2026-07-20")
    assert 350 <= len(script) <= 500
    assert "沪深300领涨" in script
    assert "公用事业" in script
    assert "高股息策略" in script
    assert "风险承受能力" in script
    assert "文件路径" not in script
    assert "sajin-daily-reports" not in script


def test_rejects_path_only_or_insufficient_response() -> None:
    response = extract_response(
        "# Cron Job: 每日基金日报\n\n## Response\n\n报告已保存。文件路径：`~/hermes/sajin-daily-reports/report.md`"
    )
    with pytest.raises(ConfigError, match="350-500"):
        build_90_second_script(response, "2026-07-20")


def test_finance_orchestrator_skips_gemini_and_generates_dry_run(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "fund-daily"
    source_dir.mkdir()
    (source_dir / "2026-07-16_18-00-00.md").write_text(SAMPLE_MD, encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "output",
        profiles_dir=Path("profiles"),
        finance_md_dir=source_dir,
        mpt_dir=tmp_path / "mpt",
    )
    monkeypatch.setattr(
        "content_pipeline.pipelines.anime.call_gemini_skill",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Gemini must not be called for finance")),
    )
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="生成每日金融视频",
            content_type="finance",
            params={"date": "2026-07-16", "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.SUCCEEDED
    assert snapshot.artifacts.images == []
    assert snapshot.artifacts.source_document is not None
    assert snapshot.artifacts.video is not None
    assert snapshot.artifacts.subtitle is not None


def test_finance_orchestrator_rejects_bad_response_before_mpt_or_upload(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "fund-daily"
    source_dir.mkdir()
    (source_dir / "2026-07-20_18-00-00.md").write_text(
        "# Cron Job: 每日基金日报\n\n## Response\n\n报告已保存。文件路径：`~/hermes/sajin-daily-reports/report.md`",
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "output", finance_md_dir=source_dir, mpt_dir=tmp_path / "mpt")
    monkeypatch.setattr(
        "content_pipeline.finance_pipeline.call_finance_mpt",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("MPT must not be called")),
    )
    monkeypatch.setattr(
        "content_pipeline.finance_pipeline.call_sau_target",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("upload must not be called")),
    )
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="生成并发布每日金融视频",
            content_type="finance",
            publish=True,
            params={"date": "2026-07-20", "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.FAILED
    assert snapshot.current_step is not None
    assert snapshot.current_step.value == "source_scan"
    assert snapshot.artifacts.video is None
    assert snapshot.artifacts.publish_results == {}


def test_finance_publish_targets_are_independent(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "fund-daily"
    source_dir.mkdir()
    (source_dir / "2026-07-16_18-00-00.md").write_text(SAMPLE_MD, encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "output", finance_md_dir=source_dir, mpt_dir=tmp_path / "mpt")

    def fake_upload(*, target, **kwargs):
        if target.platform == "douyin":
            return {"success": True, "visibility": "private"}
        raise RuntimeError("kuaishou failed")

    monkeypatch.setattr("content_pipeline.finance_pipeline.call_sau_target", fake_upload)
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="生成并发布每日金融视频",
            content_type="finance",
            publish=True,
            params={"date": "2026-07-16", "dry_run": True},
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.PARTIAL
    assert snapshot.artifacts.publish_results["douyin"]["success"] is True
    assert snapshot.artifacts.publish_results["kuaishou"]["success"] is False


def test_finance_mpt_uses_pexels_vertical_voice_and_subtitles(tmp_path: Path, monkeypatch) -> None:
    mpt_dir = tmp_path / "mpt"
    task_dir = mpt_dir / "storage" / "tasks" / "finance-20260716"
    task_dir.mkdir(parents=True)
    captured = []

    def fake_run_command(command, **kwargs):
        captured.extend(command)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "final-1.mp4").write_bytes(b"video")
        (task_dir / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:05,000\n这是一段有效的每日金融视频旁白字幕内容。\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("content_pipeline.tools.narrated_mpt_client.run_command", fake_run_command)
    result = call_finance_mpt(
        publication_date="2026-07-16",
        title="每日基金日报",
        script="这是一段有效的金融市场旁白，不是文件路径。",
        output_dir=tmp_path / "output",
        settings=Settings(mpt_dir=mpt_dir, mpt_python=Path("python")),
    )
    assert result.video.is_file()
    assert captured[captured.index("--video-source") + 1] == "pexels"
    assert captured[captured.index("--video-aspect") + 1] == "9:16"
    assert captured[captured.index("--voice-name") + 1] == "zh-CN-YunxiNeural"
    assert captured[captured.index("--voice-rate") + 1] == "1.0"
    assert "--subtitle-enabled" in captured
