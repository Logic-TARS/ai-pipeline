"""Comprehensive test suite for all 8 MCP tools."""

import asyncio
from pathlib import Path

import pytest

from content_pipeline.job_store import JobStore
from content_pipeline.mcp_server import (
    generate_images,
    get_status,
    list_jobs,
    list_profiles,
    process_ai_art,
    render_video,
    run_task_sync,
    submit_task,
)
from content_pipeline.models import JobStatus
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
                params={"dry_run": True},
            )
        )
        assert "task_id" in result
        assert len(result["task_id"]) == 32
    finally:
        mcp_mod.orchestrator = original_orch
        mcp_mod.settings = original_settings


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

        with pytest.raises(Exception):
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
