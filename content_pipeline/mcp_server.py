from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server import FastMCP

from .models import TaskInput, PublishTarget, JobSnapshot
from .orchestrator import Orchestrator
from .profiles import load_profile
from .settings import load_settings
from .tools.gemini_client import call_gemini_skill
from .tools.mpt_client import call_mpt

mcp = FastMCP("ai-popline")

settings = load_settings()
orchestrator = Orchestrator(settings=settings)

@mcp.tool()
async def submit_task(
    description: str,
    content_type: str | None = None,
    topic: str | None = None,
    publish: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Submit a new content pipeline task."""
    task = TaskInput(
        description=description,
        content_type=content_type,
        topic=topic,
        publish=publish,
        params=params or {},
    )
    task_id = orchestrator.submit(task)
    return {"task_id": task_id, "status": "queued"}


@mcp.tool()
async def get_status(task_id: str) -> dict[str, Any]:
    """Get the status of a content pipeline task."""
    try:
        return orchestrator.store.get(task_id).model_dump(mode="json")
    except FileNotFoundError:
        raise ValueError("task not found")


@mcp.tool()
async def run_task_sync(
    description: str,
    content_type: str | None = None,
    topic: str | None = None,
    publish: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit and run a content pipeline task synchronously, returning the final snapshot."""
    try:
        task = TaskInput(
            description=description,
            content_type=content_type,
            topic=topic,
            publish=publish,
            params=params or {},
        )
        task_id = orchestrator.submit(task)
        orchestrator.run(task_id)
        return orchestrator.store.get(task_id).model_dump(mode="json")
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


@mcp.tool()
async def generate_images(
    prompt: str,
    content_type: str,
    count: int = 4,
    output_dir: str | None = None,
    params: dict[str, Any] | None = None,
) -> list[str]:
    """Generate images using the Gemini skill for a given content type."""
    profile = load_profile(content_type, settings.profiles_dir)
    profile.image_gen.count = count
    out = Path(output_dir) if output_dir else settings.data_dir / "mcp_images" / prompt[:32]
    images = call_gemini_skill(
        profile=profile.image_gen,
        topic=prompt,
        params=params or {},
        output_dir=out,
        settings=settings,
    )
    return [str(p) for p in images]


@mcp.tool()
async def render_video(
    images: list[str],
    content_type: str,
    topic: str,
    params: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate a video from images using MoneyPrinterTurbo."""
    try:
        profile = load_profile(content_type, settings.profiles_dir)
        task_id = f"mcp-{uuid4().hex[:8]}"
        output_dir = settings.data_dir / "mcp_videos"
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path = call_mpt(
            task_id=task_id,
            profile=profile.video_gen,
            topic=topic,
            params=params or {"dry_run": True},
            images=[Path(p) for p in images],
            output_dir=output_dir,
            settings=settings,
        )
        return {"video": str(video_path)}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


@mcp.tool()
async def process_ai_art(
    source_dir: str,
    image_prompt: str,
    title: str,
    source_files: list[str] | None = None,
    archive_dir: str | None = None,
    failed_dir: str | None = None,
    group_size: int = 4,
    description: str = "",
    tags: list[str] | None = None,
    publish: bool = False,
    publish_targets: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process a folder of images through the AI art pipeline: edit, group, build videos, and optionally publish."""
    try:
        task_params = {
            "source_dir": source_dir,
            "image_prompt": image_prompt,
            "title": title,
            "source_files": source_files or [],
            "description": description,
            "tags": tags or [],
            "group_size": group_size,
        }
        if archive_dir is not None:
            task_params["archive_dir"] = archive_dir
        if failed_dir is not None:
            task_params["failed_dir"] = failed_dir
        if params:
            task_params.update(params)

        task = TaskInput(
            description=f"AI Art: {title}",
            content_type="ai_art",
            topic=title,
            publish=publish,
            publish_targets=[PublishTarget(**t) for t in (publish_targets or [])],
            params=task_params,
        )
        task_id = orchestrator.submit(task)
        orchestrator.run(task_id)
        return orchestrator.store.get(task_id).model_dump(mode="json")
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


@mcp.tool()
async def list_profiles() -> list[dict[str, str]]:
    """List all available content profiles."""
    return [
        {"name": path.stem, "path": str(path)}
        for path in sorted(settings.profiles_dir.glob("*.yaml"))
    ]


@mcp.tool()
async def list_jobs(limit: int = 10) -> dict[str, Any]:
    """List the most recent job summaries, sorted by creation time descending."""
    try:
        jobs_dir = settings.data_dir / "jobs"
        if not jobs_dir.is_dir():
            return {"jobs": []}

        results = []
        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if not status_file.exists():
                continue
            raw = status_file.read_text(encoding="utf-8")
            snapshot = JobSnapshot.model_validate_json(raw)
            results.append({
                "task_id": snapshot.task_id,
                "status": snapshot.status.value,
                "description": snapshot.task.description,
                "created_at": status_file.stat().st_mtime,
            })

        results.sort(key=lambda j: j["created_at"], reverse=True)
        return {"jobs": results[:limit]}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    mcp.run(transport="stdio")
