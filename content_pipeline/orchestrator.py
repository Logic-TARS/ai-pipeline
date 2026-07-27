from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai_art_pipeline import run_ai_art_pipeline
from .ai_briefing_pipeline import run_ai_briefing_pipeline
from .grouped_anime_pipeline import run_grouped_anime_pipeline
from .japanese_pipeline import run_japanese_pipeline
from .finance_pipeline import run_finance_pipeline
from .errors import PipelineError, PrivateVisibilityUnsupported, UnknownContentType
from .job_store import JobStore
from .media_validation import validate_images, validate_video
from .models import ArtifactSet, JobStatus, PipelineStep, TaskInput
from .profiles import load_profile
from .router import route_task
from .settings import Settings, load_settings
from .tools.gemini_client import call_gemini_skill
from .tools.mpt_client import call_mpt
from .tools.sau_client import call_sau_upload


class Orchestrator:
    def __init__(self, settings: Settings | None = None, store: JobStore | None = None):
        self.settings = settings or load_settings()
        self.store = store or JobStore(self.settings.data_dir)

    def submit(self, task: TaskInput) -> str:
        return self.store.create(task).task_id

    def run(self, task_id: str) -> None:
        artifacts = ArtifactSet()
        try:
            snapshot = self.store.mark_running(task_id, PipelineStep.ROUTE)
            artifacts = snapshot.artifacts
            route = route_task(snapshot.task, self.settings)
            self.store.set_route(task_id, route)
            if route.content_type == "unknown":
                raise UnknownContentType("unknown content type; no profile selected")

            if route.content_type == "ai_art":
                run_ai_art_pipeline(
                    task_id=task_id,
                    snapshot=snapshot,
                    artifacts=artifacts,
                    store=self.store,
                    settings=self.settings,
                )
                return

            elif route.content_type == "finance":
                run_finance_pipeline(
                    task_id=task_id,
                    snapshot=snapshot,
                    artifacts=artifacts,
                    store=self.store,
                    settings=self.settings,
                )
                return

            elif route.content_type == "ai_briefing":
                run_ai_briefing_pipeline(
                    task_id=task_id,
                    snapshot=snapshot,
                    artifacts=artifacts,
                    store=self.store,
                    settings=self.settings,
                )
                return

            elif route.content_type == "grouped_anime":
                run_grouped_anime_pipeline(
                    task_id=task_id,
                    snapshot=snapshot,
                    artifacts=artifacts,
                    store=self.store,
                    settings=self.settings,
                )
                return

            elif route.content_type == "japanese":
                run_japanese_pipeline(
                    task_id=task_id,
                    snapshot=snapshot,
                    artifacts=artifacts,
                    store=self.store,
                    settings=self.settings,
                )
                return

            profile = load_profile(route.content_type, self.settings.profiles_dir)
            job_dir = self.store.job_dir(task_id)

            self.store.mark_running(task_id, PipelineStep.IMAGE)
            artifacts.images = call_gemini_skill(
                profile=profile.image_gen,
                topic=route.topic,
                params=route.params,
                output_dir=job_dir / "images",
                settings=self.settings,
            )
            if not route.params.get("dry_run"):
                artifacts.validation.images = validate_images(artifacts.images, profile.image_gen.count)
            self.store.set_artifacts(task_id, artifacts)

            self.store.mark_running(task_id, PipelineStep.VIDEO)
            artifacts.video = call_mpt(
                task_id=task_id,
                profile=profile.video_gen,
                topic=route.topic,
                params=route.params,
                images=artifacts.images,
                output_dir=job_dir / "video",
                settings=self.settings,
            )
            if not route.params.get("dry_run"):
                artifacts.validation.video = validate_video(
                    artifacts.video,
                    expected_aspect=profile.video_gen.aspect,
                    require_audio=bool(profile.video_gen.voice_name),
                )
            self.store.set_artifacts(task_id, artifacts)

            if not snapshot.task.publish:
                artifacts.upload_result = {
                    "skipped": True,
                    "reason": "publish_not_requested",
                }
                self.store.set_artifacts(task_id, artifacts)
                self.store.event(task_id, "upload_skipped", {"reason": "publish_not_requested"})
                self.store.finish(task_id, JobStatus.SUCCEEDED)
                return

            self.store.mark_running(task_id, PipelineStep.UPLOAD)
            artifacts.upload_result = call_sau_upload(
                profile=profile.upload,
                topic=route.topic,
                params=route.params,
                video=artifacts.video,
                settings=self.settings,
            )
            self.store.set_artifacts(task_id, artifacts)
            self.store.finish(task_id, JobStatus.SUCCEEDED)
        except PrivateVisibilityUnsupported as exc:
            self.store.set_artifacts(task_id, artifacts)
            self.store.finish(task_id, JobStatus.BLOCKED, f"blocked_private_visibility: {exc}")
        except (PipelineError, Exception) as exc:
            self.store.set_artifacts(task_id, artifacts)
            self.store.finish(task_id, JobStatus.FAILED, str(exc))


def run_task_file(path: Path) -> dict:
    settings = load_settings()
    orchestrator = Orchestrator(settings=settings)
    task = TaskInput.model_validate(json.loads(path.read_text(encoding="utf-8")))
    task_id = orchestrator.submit(task)
    orchestrator.run(task_id)
    return orchestrator.store.get(task_id).model_dump(mode="json")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="Run one AI content pipeline task")
    parser.add_argument("--task", required=True, type=Path, help="Path to task JSON")
    args = parser.parse_args()
    result = run_task_file(args.task)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"succeeded", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
