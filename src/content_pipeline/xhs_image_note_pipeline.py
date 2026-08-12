from __future__ import annotations

from pathlib import Path

from .errors import ConfigError, MediaValidationError, PrivateVisibilityUnsupportedError
from .media_validation import validate_images
from .models import AiArtSourceResult, JobStatus, PipelineStep, XhsImageNoteParams
from .pipelines.registry import PipelineContext, PipelineMeta, register
from .tools.photo_process_client import archive_source, run_photo_process_adapter, scan_source_images
from .tools.sau_client import call_sau_xiaohongshu_note


@register(
    "xhs_image_note",
    meta=PipelineMeta(
        content_type="xhs_image_note",
        description="Photo-Process 3:4 image editing -> optional Xiaohongshu note publish",
        required_params=["source_dir", "image_prompt", "title"],
        external_tools=["Photo-Process", "SAU"],
        publish_targets=["xiaohongshu"],
    ),
)
def run_xhs_image_note_pipeline(ctx: PipelineContext) -> None:
    task_id = ctx.task_id
    snapshot = ctx.snapshot
    artifacts = ctx.artifacts
    store = ctx.store
    settings = ctx.settings
    params = XhsImageNoteParams.model_validate(ctx.route.params)
    source_dir = params.source_dir.expanduser().resolve()
    archive_dir = (params.archive_dir or (source_dir / "已处理")).expanduser().resolve()
    failed_dir = params.failed_dir.expanduser().resolve() if params.failed_dir else None
    job_dir = store.job_dir(task_id)

    store.mark_running(task_id, PipelineStep.SOURCE_SCAN)
    if not artifacts.source_results:
        sources = scan_source_images(source_dir, params.source_files)
        if not sources:
            raise ConfigError(f"Xiaohongshu image note source directory contains no supported images: {source_dir}")
        artifacts.source_results = [AiArtSourceResult(source_path=path) for path in sources]
        store.set_artifacts(task_id, artifacts)

    store.mark_running(task_id, PipelineStep.IMAGE)
    for index, record in enumerate(artifacts.source_results, start=1):
        try:
            if record.processed_path and record.processed_path.is_file():
                validation = validate_images([record.processed_path], 1)
            else:
                source = _available_source(record)
                adapter_result = run_photo_process_adapter(
                    source=source,
                    prompt=params.image_prompt,
                    output_path=job_dir / "processed" / f"{index:04d}.png",
                    settings=settings,
                )
                record.adapter_result = adapter_result
                if not adapter_result.ok:
                    raise RuntimeError(adapter_result.message or adapter_result.code.value)
                record.processed_path = Path(str(adapter_result.artifacts["processed_path"]))
                validation = validate_images([record.processed_path], 1)
            _validate_3_4(record, validation.files[0].width, validation.files[0].height)
            if record.archived_path is None:
                candidates = [Path(record.source_path)]
                if record.failed_path:
                    candidates.append(Path(record.failed_path))
                source = next((candidate for candidate in candidates if candidate.exists()), None)
                if source is not None:
                    record.archived_path = archive_source(source, archive_dir)
                    record.failed_path = None
            record.error = None
        except Exception as exc:
            record.error = str(exc)
            record.processed_path = None
            if record.failed_path is None and failed_dir:
                source = Path(record.source_path)
                if source.exists():
                    try:
                        record.failed_path = archive_source(source, failed_dir)
                    except Exception as move_exc:
                        record.error = f"{record.error}; failed to move source to failed_dir: {move_exc}"
        store.set_artifacts(task_id, artifacts)

    successful = [
        record for record in artifacts.source_results if record.processed_path and record.processed_path.is_file()
    ]
    if not successful:
        raise ConfigError("Photo-Process did not produce any usable 3:4 Xiaohongshu images")
    artifacts.images = [Path(record.processed_path) for record in successful if record.processed_path]
    artifacts.validation.images = validate_images(artifacts.images, len(artifacts.images))

    if not snapshot.task.publish:
        artifacts.upload_result = {"skipped": True, "reason": "publish_not_requested"}
        store.set_artifacts(task_id, artifacts)
        store.event(task_id, "upload_skipped", {"reason": "publish_not_requested"})
    else:
        if not snapshot.task.publish_targets:
            raise ConfigError("publish=true requires a Xiaohongshu publish target for an image note task")
        invalid_targets = [
            target.platform for target in snapshot.task.publish_targets if target.platform != "xiaohongshu"
        ]
        if invalid_targets:
            raise ConfigError("xhs_image_note only supports xiaohongshu publish targets")
        store.mark_running(task_id, PipelineStep.UPLOAD)
        for target in snapshot.task.publish_targets:
            key = f"{target.platform}:{target.account}"
            try:
                result = call_sau_xiaohongshu_note(
                    images=artifacts.images,
                    title=params.title,
                    note=params.note or snapshot.task.description,
                    tags=params.tags,
                    account=target.account,
                    settings=settings,
                    schedule=params.schedule,
                    debug=params.debug,
                    headed=params.headed,
                    dry_run=params.dry_run or bool(snapshot.task.params.get("dry_run")),
                )
                artifacts.publish_results[key] = {"status": "succeeded", **result}
            except PrivateVisibilityUnsupportedError as exc:
                artifacts.publish_results[key] = {"status": "blocked", "error": str(exc)}
            except Exception as exc:
                artifacts.publish_results[key] = {"status": "failed", "error": str(exc)}
            store.set_artifacts(task_id, artifacts)
        artifacts.upload_result = {"publish_results": artifacts.publish_results}

    store.set_artifacts(task_id, artifacts)
    partial_reasons = _partial_reasons(artifacts.source_results, snapshot.task.publish, artifacts.publish_results)
    if partial_reasons:
        store.finish(task_id, JobStatus.PARTIAL, "; ".join(partial_reasons))
    else:
        store.finish(task_id, JobStatus.SUCCEEDED)


def _available_source(record: AiArtSourceResult) -> Path:
    for candidate in (record.source_path, record.archived_path, record.failed_path):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise ConfigError(f"source image is unavailable: {record.source_path}")


def _validate_3_4(record: AiArtSourceResult, width: int, height: int) -> None:
    target_aspect = None
    if record.adapter_result:
        target_aspect = record.adapter_result.artifacts.get("target_aspect_ratio")
    if target_aspect == "3:4":
        return
    actual = width / height
    if abs(actual - 0.75) > 0.02:
        raise MediaValidationError(f"processed image aspect ratio {width}:{height} does not match 3:4")


def _partial_reasons(
    source_results: list[AiArtSourceResult],
    publish: bool,
    publish_results: dict[str, dict[str, object]],
) -> list[str]:
    reasons = [f"{Path(record.source_path).name}: {record.error}" for record in source_results if record.error]
    if publish:
        for key, result in publish_results.items():
            if result.get("status") != "succeeded":
                reasons.append(f"upload {key}: {result.get('error', result.get('status'))}")
    return reasons
