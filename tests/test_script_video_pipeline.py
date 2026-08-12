import json
from pathlib import Path

from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


def _script() -> str:
    body = (
        "今天关注金融市场的三个方向。黄金价格受美元、实际利率与避险情绪共同影响，观察行情时需要区分实时价格和滞后宏观指标。"
        "债券市场则需要结合不同期限收益率变化理解价格表现，不能只看单一数据。宏观方面，通胀、采购经理指数、货币供应和社会融资反映的周期并不完全同步。"
        "如果关注个股，还应同时核对行情时间、涨跌幅、成交信息与市场状态，避免把短期波动写成确定趋势。制作内容时应保留数据日期和来源，遇到回填或滞后字段要明确说明。"
        "不同市场的交易时间和统计口径也可能不同，横向比较前要先确认单位、频率和更新时间。新闻只用于解释情绪，不能代替价格、成交和基本面数据。"
        "口播中引用结论时，应先描述已确认的事实，再说明可能影响，避免使用必然上涨、确定反转等没有证据支持的表达。"
        "面对市场变化，应结合自身投资期限、仓位和风险承受能力独立判断，不根据单条资讯追涨杀跌。"
    )
    return body + "以上内容仅为市场信息整理，不构成投资建议。"


def test_script_video_pipeline_generates_guarded_dry_run_artifacts(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "output", mpt_dir=tmp_path / "mpt")
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="内容工作台口播视频",
            content_type="script_video",
            params={"title": "今日金融资讯", "script": _script(), "dry_run": True, "voice_rate": 0.85},
        )
    )

    orchestrator.run(task_id)

    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.SUCCEEDED
    assert snapshot.artifacts.script_path is not None and snapshot.artifacts.script_path.is_file()
    assert snapshot.artifacts.video is not None and snapshot.artifacts.video.is_file()
    assert snapshot.artifacts.subtitle is not None and snapshot.artifacts.subtitle.is_file()
    assert snapshot.artifacts.upload_result == {"skipped": True, "reason": "publish_not_requested"}
    assert snapshot.artifacts.manifest_path is not None
    manifest = json.loads(snapshot.artifacts.manifest_path.read_text(encoding="utf-8"))
    assert manifest["voice_rate"] == 0.85
    assert snapshot.progress is not None
    assert snapshot.progress.percent == 100
    assert snapshot.progress.phase == "完成"
    events = orchestrator.store.events_path(task_id).read_text(encoding="utf-8")
    assert '"event": "progress_updated"' in events
    assert str(settings.data_dir) not in events


def test_script_video_pipeline_rejects_local_file_references(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "output", mpt_dir=tmp_path / "mpt")
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="包含本地文件路径",
            content_type="script_video",
            params={"title": "今日资讯", "script": "市场信息。" * 72 + r" C:\private\source.md ", "dry_run": True},
        )
    )

    orchestrator.run(task_id)

    snapshot = orchestrator.store.get(task_id)
    assert snapshot.status == JobStatus.FAILED
    assert "local file reference" in (snapshot.error or "")
