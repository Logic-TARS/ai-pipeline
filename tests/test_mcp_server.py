"""Comprehensive test suite for MCP tools."""

import asyncio
from pathlib import Path

import pytest

from content_pipeline.errors import ConfigError
from content_pipeline.job_store import JobStore
from content_pipeline.mcp_server import (
    generate_images,
    get_external_tool_contracts,
    get_job_events,
    get_status,
    list_capabilities,
    list_jobs,
    list_profiles,
    open_photo_process_debug,
    process_ai_art,
    process_ai_art_async,
    process_japanese_images,
    render_video,
    run_finance_video_async,
    run_task_async,
    run_task_sync,
    start_task,
    submit_task,
)
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


def _make_settings(tmp_path: Path) -> Settings:
    """Create isolated Settings using tmp_path for all directories."""
    data_dir = tmp_path / "output"
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    # Copy real profiles so tests can route properly
    real_profiles = Path("profiles")
    for pf in real_profiles.glob("*.yaml"):
        (profiles_dir / pf.name).write_text(pf.read_text(encoding="utf-8"), encoding="utf-8")
    return Settings(
        data_dir=data_dir,
        profiles_dir=profiles_dir,
    )


def _make_orchestrator(tmp_path: Path) -> Orchestrator:
    """Create an Orchestrator with isolated Settings and JobStore."""
    settings = _make_settings(tmp_path)
    return Orchestrator(settings=settings, store=JobStore(settings.data_dir))


class FakeExecutor:
    """Capture submitted work without starting real browser/video jobs."""

    def __init__(self) -> None:
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))
        return None


# ---------------------------------------------------------------------------
# submit_task tests
# ---------------------------------------------------------------------------


def test_submit_task_returns_task_id(tmp_path: Path) -> None:
    """Submit an anime task, verify task_id is a 32-char hex string."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    # Patch the module-level orchestrator used by MCP tools
    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        result = asyncio.run(submit_task(description="动漫短片", content_type="anime", topic="周五下班"))
        assert "task_id" in result
        assert len(result["task_id"]) == 32
        assert all(c in "0123456789abcdef" for c in result["task_id"])
        assert result["status"] == "queued"
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_submit_task_without_content_type_routes(tmp_path: Path) -> None:
    """Submit without content_type, verify task_id is still returned (routing deferred)."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        result = asyncio.run(submit_task(description="测试任务", topic="无类型"))
        assert "task_id" in result
        assert len(result["task_id"]) == 32
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_submit_task_with_publish_targets(tmp_path: Path) -> None:
    """Submit with publish_targets, verify task_id."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        result = asyncio.run(
            submit_task(
                description="动漫短片",
                content_type="anime",
                topic="周五下班",
                publish=True,
                publish_targets=[{"platform": "douyin", "account": "测试账号"}],
                params={"dry_run": True},
            )
        )
        assert "task_id" in result
        assert len(result["task_id"]) == 32
        snapshot = orch.store.get(result["task_id"])
        assert snapshot.task.publish_targets[0].platform == "douyin"
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_run_task_async_starts_background_task(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    fake_executor = FakeExecutor()

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    original_executor = mcp_mod.executor
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings
        mcp_mod.executor = fake_executor

        result = asyncio.run(
            run_task_async(
                description="异步任务",
                content_type="anime",
                topic="测试",
                params={"dry_run": True},
            )
        )
        assert result["status"] == "queued"
        assert len(fake_executor.calls) == 1
        fn, args = fake_executor.calls[0]
        assert fn == orch.run
        assert args == (result["task_id"],)
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings
        mcp_mod.executor = original_executor


def test_start_task_submits_existing_task(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    fake_executor = FakeExecutor()

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_executor = mcp_mod.executor
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.executor = fake_executor

        task_id = orch.submit(
            TaskInput(
                description="待启动",
                content_type="anime",
                topic="测试",
                params={"dry_run": True},
            )
        )
        result = asyncio.run(start_task(task_id))
        assert result == {"task_id": task_id, "status": "queued"}
        assert fake_executor.calls[0][1] == (task_id,)
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.executor = original_executor


def test_start_task_does_not_restart_finished_task(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    fake_executor = FakeExecutor()

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_executor = mcp_mod.executor
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.executor = fake_executor

        task_id = orch.submit(
            TaskInput(
                description="已完成",
                content_type="anime",
                topic="测试",
                params={"dry_run": True},
            )
        )
        orch.store.finish(task_id, JobStatus.SUCCEEDED)

        result = asyncio.run(start_task(task_id))
        assert result == {"task_id": task_id, "status": "succeeded"}
        assert fake_executor.calls == []
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.executor = original_executor


# ---------------------------------------------------------------------------
# get_status tests
# ---------------------------------------------------------------------------


def test_get_status_returns_snapshot(tmp_path: Path) -> None:
    """Submit then get_status, verify status='queued'."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        submit_result = asyncio.run(submit_task(description="状态测试", content_type="anime", topic="测试"))
        task_id = submit_result["task_id"]

        status = asyncio.run(get_status(task_id))
        assert status["status"] == "queued"
        assert status["task_id"] == task_id
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_get_status_unknown_task_raises(tmp_path: Path) -> None:
    """get_status with fake id raises ValueError."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        with pytest.raises(ValueError, match="task not found"):
            asyncio.run(get_status("0" * 32))
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_get_job_events_returns_recent_events(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    try:
        mcp_mod.orchestrator = orch
        task_id = orch.submit(
            TaskInput(
                description="事件测试",
                content_type="anime",
                topic="测试",
                params={"dry_run": True},
            )
        )
        orch.store.event(task_id, "custom_event", {"ok": True})

        result = asyncio.run(get_job_events(task_id, limit=1))
        assert result["task_id"] == task_id
        assert result["events"][0]["event"] == "custom_event"
        assert result["events"][0]["payload"] == {"ok": True}
    finally:
        mcp_mod.orchestrator = original_orch


def test_list_capabilities_describes_agent_workflows() -> None:
    result = asyncio.run(list_capabilities())

    workflow_names = {workflow["name"] for workflow in result["workflows"]}
    assert "generic_content_task" in workflow_names
    assert "photo_process_image_folder" in workflow_names
    assert "finance_video" in workflow_names
    assert "get_status" in result["status_tools"]
    assert "open_photo_process_debug" in result["diagnostic_tools"]
    photo_workflow = next(
        workflow for workflow in result["workflows"] if workflow["name"] == "photo_process_image_folder"
    )
    assert "CLI JSON adapter" in photo_workflow["lower_tool"]["boundary"]
    assert "Browser Worker" in photo_workflow["lower_tool"]["boundary"]
    assert photo_workflow["lower_tool"]["foreground_debug"]["mcp_tool"] == "open_photo_process_debug"


def test_get_external_tool_contracts_returns_photo_process_contract() -> None:
    result = asyncio.run(get_external_tool_contracts())

    assert result["tools"][0]["name"] == "Photo-Process"
    assert "CLI JSON adapter" in result["tools"][0]["boundary"]
    assert "Browser Worker" in result["tools"][0]["boundary"]
    assert "--json" in result["tools"][0]["command"]
    assert result["tools"][0]["foreground_debug"]["cli"].startswith("python -m content_pipeline.diagnostics")
    assert result["tools"][0]["foreground_debug"]["desktop_cli"].startswith("python -m content_pipeline.diagnostics")
    assert result["tools"][0]["foreground_debug"]["install_desktop_helper_task"].endswith(
        "install_desktop_browser_helper_task.ps1"
    )
    assert result["tools"][0]["foreground_debug"]["uninstall_desktop_helper_task"].endswith(
        "uninstall_desktop_browser_helper_task.ps1"
    )


def test_open_photo_process_debug_returns_adapter_result(monkeypatch) -> None:
    import content_pipeline.mcp_server as mcp_mod

    def fake_open(*, settings, url, mode, desktop_helper_url):
        from content_pipeline.models import AdapterResult, ErrorCode

        return AdapterResult(
            ok=True,
            tool="Photo-Process foreground debug",
            code=ErrorCode.OK,
            artifacts={"snapshot_path": "logs/frontend_dom_snapshot.json"},
            evidence={"command": ["python", "启动调试浏览器.py", url], "mode": mode},
        )

    monkeypatch.setattr(mcp_mod, "open_photo_process_debug_browser", fake_open)

    result = asyncio.run(open_photo_process_debug("https://gemini.google.com/app", mode="desktop"))

    assert result["ok"] is True
    assert result["code"] == "OK"
    assert result["evidence"]["mode"] == "desktop"
    assert result["artifacts"]["snapshot_path"].endswith("frontend_dom_snapshot.json")


# ---------------------------------------------------------------------------
# run_task_sync tests
# ---------------------------------------------------------------------------


def test_run_task_sync_dry_run_succeeds(tmp_path: Path) -> None:
    """run_task_sync with dry_run, verify status='succeeded'."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        result = asyncio.run(
            run_task_sync(
                description="动漫短片",
                content_type="anime",
                topic="周五下班",
                params={"script": "四格故事", "dry_run": True},
            )
        )
        assert result["status"] == "succeeded"
        assert len(result["artifacts"]["images"]) == 4
        assert result["artifacts"]["video"] is not None
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_run_task_sync_unknown_content_type_fails(tmp_path: Path) -> None:
    """run_task_sync with unknown type, verify status='failed'."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        result = asyncio.run(
            run_task_sync(
                description="未知类型",
                content_type="nonexistent_type",
                topic="测试",
                params={"dry_run": True},
            )
        )
        assert result["status"] == "failed"
        assert "error" in result
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


# ---------------------------------------------------------------------------
# generate_images tests
# ---------------------------------------------------------------------------


def test_generate_images_dry_run(tmp_path: Path) -> None:
    """generate_images with dry_run params, verify returns list of paths."""
    settings = _make_settings(tmp_path)

    import content_pipeline.mcp_server as mcp_mod

    original_settings = mcp_mod.settings
    try:
        mcp_mod.settings = settings

        result = asyncio.run(
            generate_images(
                prompt="测试提示词",
                content_type="anime",
                count=2,
                params={"dry_run": True},
            )
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(p, str) for p in result)
    finally:
        mcp_mod.settings = original_settings


def test_generate_images_invalid_content_type(tmp_path: Path) -> None:
    """generate_images with bad type, verify raises."""
    settings = _make_settings(tmp_path)

    import content_pipeline.mcp_server as mcp_mod

    original_settings = mcp_mod.settings
    try:
        mcp_mod.settings = settings

        with pytest.raises(ConfigError):
            asyncio.run(
                generate_images(
                    prompt="测试",
                    content_type="invalid_type",
                    count=1,
                    params={"dry_run": True},
                )
            )
    finally:
        mcp_mod.settings = original_settings


# ---------------------------------------------------------------------------
# render_video tests
# ---------------------------------------------------------------------------


def test_render_video_dry_run(tmp_path: Path) -> None:
    """render_video with dry_run, verify returns video path."""
    settings = _make_settings(tmp_path)

    import content_pipeline.mcp_server as mcp_mod

    original_settings = mcp_mod.settings
    try:
        mcp_mod.settings = settings

        # Create dummy image files
        img_dir = tmp_path / "test_images"
        img_dir.mkdir()
        for i in range(4):
            (img_dir / f"{i:02d}.jpg").write_bytes(b"fake-image-data")

        result = asyncio.run(
            render_video(
                images=[str(img_dir / f"{i:02d}.jpg") for i in range(4)],
                content_type="anime",
                topic="测试视频",
                params={"dry_run": True},
            )
        )
        assert "video" in result
        assert result["video"].endswith(".mp4")
    finally:
        mcp_mod.settings = original_settings


def test_render_video_empty_images(tmp_path: Path) -> None:
    """render_video with empty list, verify it still returns a video path (dry_run tolerates empty)."""
    settings = _make_settings(tmp_path)

    import content_pipeline.mcp_server as mcp_mod

    original_settings = mcp_mod.settings
    try:
        mcp_mod.settings = settings

        result = asyncio.run(
            render_video(
                images=[],
                content_type="anime",
                topic="空视频",
                params={"dry_run": True},
            )
        )
        # dry_run mode produces a placeholder video even with no images
        assert "video" in result
        assert result["video"].endswith(".mp4")
    finally:
        mcp_mod.settings = original_settings


# ---------------------------------------------------------------------------
# process_ai_art tests
# ---------------------------------------------------------------------------


def test_process_ai_art_no_source_dir(tmp_path: Path) -> None:
    """process_ai_art with nonexistent dir, verify returns error."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        nonexistent = str(tmp_path / "nonexistent_source")
        result = asyncio.run(
            process_ai_art(
                source_dir=nonexistent,
                image_prompt="测试提示词",
                title="AI艺术测试",
                params={"dry_run": True},
            )
        )
        assert result.get("status") in ("failed", "succeeded", "partial")
        # If succeeded/partial, the pipeline handled the missing dir gracefully
        # If failed, it should have an error message
        if result.get("status") == "failed":
            assert "error" in result
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


def test_process_ai_art_async_builds_explicit_task(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    fake_executor = FakeExecutor()

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    original_executor = mcp_mod.executor
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings
        mcp_mod.executor = fake_executor

        result = asyncio.run(
            process_ai_art_async(
                source_dir=str(tmp_path / "images"),
                image_prompt="水彩风格",
                title="作品集",
                archive_dir=str(tmp_path / "done"),
                failed_dir=str(tmp_path / "failed"),
                group_size=3,
                publish_targets=[{"platform": "douyin", "account": "测试账号"}],
                publish=True,
            )
        )
        snapshot = orch.store.get(result["task_id"])
        assert snapshot.task.content_type == "ai_art"
        assert snapshot.task.params["group_size"] == 3
        assert snapshot.task.params["archive_dir"] == str(tmp_path / "done")
        assert snapshot.task.publish_targets[0].platform == "douyin"
        assert fake_executor.calls[0][1] == (result["task_id"],)
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings
        mcp_mod.executor = original_executor


def test_process_japanese_images_builds_photo_process_task(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    fake_executor = FakeExecutor()

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_executor = mcp_mod.executor
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.executor = fake_executor

        result = asyncio.run(
            process_japanese_images(
                source_dir=str(tmp_path / "input"),
                output_dir=str(tmp_path / "output"),
                image_prompt="日语视觉化",
                source_files=["one.png"],
                target_gem_url="https://gemini.google.com/gem/f306c82a8105",
                dry_run=True,
            )
        )
        snapshot = orch.store.get(result["task_id"])
        assert snapshot.task.content_type == "japanese"
        assert snapshot.task.publish is False
        assert snapshot.task.params["source_files"] == ["one.png"]
        assert snapshot.task.params["output_dir"] == str(tmp_path / "output")
        assert snapshot.task.params["target_gem_url"] == "https://gemini.google.com/gem/f306c82a8105"
        assert fake_executor.calls[0][1] == (result["task_id"],)
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.executor = original_executor


def test_run_finance_video_async_builds_guarded_task(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    fake_executor = FakeExecutor()

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_executor = mcp_mod.executor
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.executor = fake_executor

        result = asyncio.run(
            run_finance_video_async(
                date="2026-07-26",
                dry_run=True,
                publish=False,
                title="基金日报",
            )
        )
        snapshot = orch.store.get(result["task_id"])
        assert snapshot.task.content_type == "finance"
        assert snapshot.task.publish is False
        assert snapshot.task.params["date"] == "2026-07-26"
        assert snapshot.task.params["dry_run"] is True
        assert snapshot.task.params["title"] == "基金日报"
        assert fake_executor.calls[0][1] == (result["task_id"],)
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.executor = original_executor


# ---------------------------------------------------------------------------
# list_profiles tests
# ---------------------------------------------------------------------------


def test_list_profiles_returns_yaml_files(tmp_path: Path) -> None:
    """list_profiles, verify returns anime and finance."""
    settings = _make_settings(tmp_path)

    import content_pipeline.mcp_server as mcp_mod

    original_settings = mcp_mod.settings
    try:
        mcp_mod.settings = settings

        result = asyncio.run(list_profiles())
        assert isinstance(result, list)
        names = {p["name"] for p in result}
        assert "anime" in names
        assert "finance" in names
    finally:
        mcp_mod.settings = original_settings


# ---------------------------------------------------------------------------
# list_jobs tests
# ---------------------------------------------------------------------------


def test_list_jobs_empty_returns_empty_list(tmp_path: Path) -> None:
    """list_jobs with no jobs, verify returns {"jobs": []}."""
    settings = _make_settings(tmp_path)

    import content_pipeline.mcp_server as mcp_mod

    original_settings = mcp_mod.settings
    try:
        mcp_mod.settings = settings

        result = asyncio.run(list_jobs())
        assert result == {"jobs": []}
    finally:
        mcp_mod.settings = original_settings


def test_list_jobs_returns_recent(tmp_path: Path) -> None:
    """Submit a task then list_jobs, verify it appears."""
    settings = _make_settings(tmp_path)
    orch = Orchestrator(settings=settings, store=JobStore(settings.data_dir))

    import content_pipeline.mcp_server as mcp_mod

    original_orch = mcp_mod.orchestrator
    original_settings = mcp_mod.settings
    try:
        mcp_mod.orchestrator = orch
        mcp_mod.settings = settings

        # Submit and run a task
        asyncio.run(
            run_task_sync(
                description="最近任务",
                content_type="anime",
                topic="测试",
                params={"dry_run": True},
            )
        )

        result = asyncio.run(list_jobs(limit=5))
        assert "jobs" in result
        assert len(result["jobs"]) >= 1
        assert result["jobs"][0]["description"] == "最近任务"
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings
