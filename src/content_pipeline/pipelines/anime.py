"""Anime pipeline: Gemini image gen -> MPT video -> optional Bilibili publish."""

from __future__ import annotations

from content_pipeline.media_validation import validate_images, validate_video
from content_pipeline.models import JobStatus, PipelineStep
from content_pipeline.pipelines.registry import PipelineContext, PipelineMeta, register
from content_pipeline.profiles import load_profile
from content_pipeline.tools.gemini_client import call_gemini_skill
from content_pipeline.tools.mpt_client import call_mpt
from content_pipeline.tools.sau_client import call_sau_upload

__all__ = ["run_anime_pipeline"]


@register(
    "anime",
    meta=PipelineMeta(
        content_type="anime",
        description="Gemini image generation -> MPT video -> optional Bilibili publish",
        required_params=[],
        external_tools=["Gemini", "MoneyPrinterTurbo"],
        publish_targets=["bilibili"],
    ),
)
def run_anime_pipeline(ctx: PipelineContext) -> None:
    """Run the anime pipeline using a loaded profile."""
    profile = load_profile(ctx.route.content_type, ctx.settings.profiles_dir)
    job_dir = ctx.store.job_dir(ctx.task_id)
    topic = ctx.route.topic
    params = ctx.route.params

    ctx.store.mark_running(ctx.task_id, PipelineStep.IMAGE)
    ctx.artifacts.images = call_gemini_skill(
        profile=profile.image_gen,
        topic=topic,
        params=params,
        output_dir=job_dir / "images",
        settings=ctx.settings,
    )
    if not params.get("dry_run"):
        ctx.artifacts.validation.images = validate_images(ctx.artifacts.images, profile.image_gen.count)
    ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)

    ctx.store.mark_running(ctx.task_id, PipelineStep.VIDEO)
    ctx.artifacts.video = call_mpt(
        task_id=ctx.task_id,
        profile=profile.video_gen,
        topic=topic,
        params=params,
        images=ctx.artifacts.images,
        output_dir=job_dir / "video",
        settings=ctx.settings,
    )
    if not params.get("dry_run"):
        ctx.artifacts.validation.video = validate_video(
            ctx.artifacts.video,
            expected_aspect=profile.video_gen.aspect,
            require_audio=bool(profile.video_gen.voice_name),
        )
    ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)

    if not ctx.snapshot.task.publish:
        ctx.artifacts.upload_result = {
            "skipped": True,
            "reason": "publish_not_requested",
        }
        ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)
        ctx.store.event(ctx.task_id, "upload_skipped", {"reason": "publish_not_requested"})
        ctx.store.finish(ctx.task_id, JobStatus.SUCCEEDED)
        return

    ctx.store.mark_running(ctx.task_id, PipelineStep.UPLOAD)
    ctx.artifacts.upload_result = call_sau_upload(
        profile=profile.upload,
        topic=topic,
        params=params,
        video=ctx.artifacts.video,
        settings=ctx.settings,
    )
    ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)
    ctx.store.finish(ctx.task_id, JobStatus.SUCCEEDED)
