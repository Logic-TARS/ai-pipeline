from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Trigger pipeline registrations at import time
from . import pipelines  # noqa: F401
from .errors import PipelineError, PrivateVisibilityUnsupportedError, UnknownContentTypeError
from .job_store import JobStore
from .models import ArtifactSet, JobStatus, PipelineStep, TaskInput
from .pipeline_config import apply_pipeline_defaults
from .pipelines.registry import PipelineContext, get_pipeline
from .router import route_task
from .settings import Settings, load_settings


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
            route = apply_pipeline_defaults(route, settings=self.settings, task_id=task_id)
            self.store.set_route(task_id, route)
            if route.content_type == "unknown":
                raise UnknownContentTypeError("unknown content type; no profile selected")

            # Registry-based dispatch
            pipeline = get_pipeline(route.content_type)
            if pipeline is not None:
                ctx = PipelineContext(
                    task_id=task_id,
                    snapshot=snapshot,
                    route=route,
                    artifacts=artifacts,
                    store=self.store,
                    settings=self.settings,
                )
                pipeline(ctx)
                return

            raise UnknownContentTypeError(f"no pipeline registered for content type: {route.content_type}")
        except PrivateVisibilityUnsupportedError as exc:
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
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
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
