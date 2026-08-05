from __future__ import annotations

import re

from content_pipeline.errors import ConfigError
from content_pipeline.media_validation import validate_video
from content_pipeline.models import JobStatus, PipelineStep, PublishTarget, ScriptVideoParams
from content_pipeline.pipelines.registry import PipelineContext, PipelineMeta, register
from content_pipeline.tools.narrated_mpt_client import (
    call_narrated_mpt,
    looks_like_file_reference,
    validate_spoken_subtitle,
)
from content_pipeline.tools.sau_client import call_sau_target


@register(
    "script_video",
    meta=PipelineMeta(
        content_type="script_video",
        description="Reviewed narration script -> narrated 9:16 MPT video -> optional private upload",
        required_params=["title", "script"],
        external_tools=["MoneyPrinterTurbo", "social-auto-upload"],
        publish_targets=["douyin", "kuaishou"],
    ),
)
def run_script_video_pipeline(ctx: PipelineContext) -> None:
    params = ScriptVideoParams.model_validate(ctx.route.params)
    script = params.script.strip()
    if looks_like_file_reference(script) or re.search(r"(?:[A-Za-z]:[\\/]|/home/).+\.(?:md|txt|json)", script):
        raise ConfigError("script video narration cannot contain a local file reference")

    job_dir = ctx.store.job_dir(ctx.task_id)
    ctx.store.mark_running(ctx.task_id, PipelineStep.SOURCE_SCAN)
    script_path = job_dir / "narration_script.txt"
    script_path.write_text(script, encoding="utf-8")
    ctx.artifacts.narration_script = script
    ctx.artifacts.script_path = script_path
    ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)

    ctx.store.mark_running(ctx.task_id, PipelineStep.VIDEO)
    result = call_narrated_mpt(
        task_name=f"content-{ctx.task_id}",
        title=params.title,
        script=script,
        output_dir=job_dir / "video",
        settings=ctx.settings,
        dry_run=params.dry_run,
        force_regenerate=params.force_regenerate,
    )
    ctx.artifacts.video = result.video
    ctx.artifacts.subtitle = result.subtitle
    ctx.artifacts.mpt_task_dir = result.task_dir
    ctx.artifacts.manifest_path = result.manifest
    validate_spoken_subtitle(result.subtitle)
    if not params.dry_run:
        ctx.artifacts.validation.video = validate_video(result.video, expected_aspect="9:16", require_audio=True)
    if not ctx.snapshot.task.publish:
        ctx.artifacts.upload_result = {"skipped": True, "reason": "publish_not_requested"}
        ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)
        ctx.store.event(ctx.task_id, "upload_skipped", {"reason": "publish_not_requested"})
        ctx.store.finish(ctx.task_id, JobStatus.SUCCEEDED)
        return

    targets = ctx.snapshot.task.publish_targets or [
        PublishTarget(platform="douyin", account=params.douyin_account),
        PublishTarget(platform="kuaishou", account=params.kuaishou_account),
    ]
    ctx.store.mark_running(ctx.task_id, PipelineStep.UPLOAD)
    for target in targets:
        if target.platform not in {"douyin", "kuaishou"}:
            ctx.artifacts.publish_results[target.platform] = {
                "success": False,
                "error": "script video publishing supports only douyin and kuaishou",
            }
            continue
        try:
            publish_result = call_sau_target(
                target=target,
                video=result.video.resolve(),
                title=params.title,
                desc=params.description,
                tags=params.tags,
                settings=ctx.settings,
                dry_run=params.dry_run,
            )
            ctx.artifacts.publish_results[target.platform] = publish_result
        except Exception as exc:
            ctx.artifacts.publish_results[target.platform] = {"success": False, "error": str(exc)}
        ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)
        ctx.store.event(
            ctx.task_id,
            "publish_target_finished",
            {"platform": target.platform, "result": ctx.artifacts.publish_results[target.platform]},
        )

    ctx.artifacts.upload_result = {"targets": ctx.artifacts.publish_results, "visibility": "private"}
    ctx.store.set_artifacts(ctx.task_id, ctx.artifacts)
    failures = [name for name, publish_result in ctx.artifacts.publish_results.items() if not publish_result.get("success")]
    if failures:
        ctx.store.finish(ctx.task_id, JobStatus.PARTIAL, "publish_failed: " + ", ".join(failures))
    else:
        ctx.store.finish(ctx.task_id, JobStatus.SUCCEEDED)
