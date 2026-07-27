from __future__ import annotations

import shutil
from pathlib import Path

from .errors import ConfigError
from .job_store import JobStore
from .media_validation import validate_images
from .models import (
    AiArtSourceResult,
    ArtifactSet,
    JapaneseParams,
    JobSnapshot,
    JobStatus,
    PipelineStep,
)
from .pipelines.registry import PipelineMeta, register
from .settings import Settings
from .tools.photo_process_client import run_photo_process_adapter, scan_source_images

JAPANESE_TARGET_GEM_NAME = "日语视觉化"
JAPANESE_TARGET_GEM_URL = "https://gemini.google.com/gem/f306c82a8105"


@register(
    "japanese",
    meta=PipelineMeta(
        content_type="japanese",
        description="Photo-Process Japanese Visualization Gem editing -> local image output only (no video/publish)",
        required_params=["source_dir"],
        external_tools=["Photo-Process"],
        publish_targets=[],
    ),
)
def run_japanese_pipeline(
    *,
    task_id: str,
    snapshot: JobSnapshot,
    artifacts: ArtifactSet,
    store: JobStore,
    settings: Settings,
) -> None:
    params = JapaneseParams.model_validate(snapshot.task.params)
    source_dir = params.source_dir.expanduser().resolve()
    output_dir = (params.output_dir or (source_dir / "日语改图")).expanduser().resolve()
    job_dir = store.job_dir(task_id)
    if output_dir == source_dir:
        raise ConfigError("japanese output_dir must be different from source_dir")

    store.mark_running(task_id, PipelineStep.SOURCE_SCAN)
    if not artifacts.source_results:
        sources = scan_source_images(source_dir, params.source_files)
        if not sources:
            raise ConfigError(f"Japanese source directory contains no supported images: {source_dir}")
        artifacts.source_results = [AiArtSourceResult(source_path=path) for path in sources]
        store.set_artifacts(task_id, artifacts)

    store.mark_running(task_id, PipelineStep.IMAGE)
    for index, record in enumerate(artifacts.source_results, start=1):
        try:
            output_path = output_dir / f"{index:04d}.png"
            if record.processed_path and Path(record.processed_path).is_file():
                validate_images([Path(record.processed_path)], 1)
            elif params.dry_run:
                record.processed_path = _copy_for_dry_run(Path(record.source_path), output_path)
            else:
                staged_source = _stage_source_copy(
                    Path(record.source_path),
                    job_dir / "photo_process_sources",
                    index,
                )
                adapter_result = run_photo_process_adapter(
                    source=staged_source,
                    prompt=params.image_prompt,
                    output_path=output_path,
                    settings=settings,
                    target_gem_name=JAPANESE_TARGET_GEM_NAME,
                    target_gem_url=params.target_gem_url or JAPANESE_TARGET_GEM_URL,
                )
                if not adapter_result.ok and adapter_result.code.value == "GEM_ACCESS_FAILED":
                    adapter_result = run_photo_process_adapter(
                        source=staged_source,
                        prompt=params.image_prompt,
                        output_path=output_path,
                        settings=settings,
                        target_gem_name=JAPANESE_TARGET_GEM_NAME,
                        target_gem_url=None,
                    )
                record.adapter_result = adapter_result
                if not adapter_result.ok:
                    raise RuntimeError(adapter_result.message or adapter_result.code.value)
                record.processed_path = Path(str(adapter_result.artifacts["processed_path"]))
            record.error = None
        except Exception as exc:
            record.error = str(exc)
        store.set_artifacts(task_id, artifacts)

    successful = [
        record for record in artifacts.source_results if record.processed_path and Path(record.processed_path).is_file()
    ]
    if not successful:
        raise ConfigError("Photo-Process did not produce any usable Japanese images")

    artifacts.images = [Path(record.processed_path) for record in successful if record.processed_path]
    artifacts.validation.images = validate_images(artifacts.images, len(artifacts.images))
    artifacts.video = None
    artifacts.groups = []
    artifacts.upload_result = {"skipped": True, "reason": "local_image_pipeline"}
    store.set_artifacts(task_id, artifacts)

    failed = [record for record in artifacts.source_results if record.error]
    if failed:
        store.finish(task_id, JobStatus.PARTIAL, f"{len(failed)} image(s) failed")
    else:
        store.finish(task_id, JobStatus.SUCCEEDED)


def _copy_for_dry_run(source: Path, output_path: Path) -> Path:
    target = output_path.with_suffix(source.suffix.lower())
    if target.is_file():
        validate_images([target], 1)
        return target
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    validate_images([target], 1)
    return target


def _stage_source_copy(source: Path, stage_dir: Path, index: int) -> Path:
    stage_dir.mkdir(parents=True, exist_ok=True)
    target = stage_dir / f"{index:04d}{source.suffix.lower()}"
    if target.is_file():
        validate_images([target], 1)
        return target
    shutil.copy2(source, target)
    validate_images([target], 1)
    return target
