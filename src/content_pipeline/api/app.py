from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.pipelines.registry import list_pipelines
from content_pipeline.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application with isolated settings and executor state."""
    resolved_settings = settings or load_settings()
    orchestrator = Orchestrator(settings=resolved_settings)
    executor = ThreadPoolExecutor(max_workers=2)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.orchestrator = orchestrator
        app.state.executor = executor
        try:
            yield
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="AI Popline Content Pipeline", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.orchestrator = orchestrator
    app.state.executor = executor

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "ai-popline"}

    @app.get("/ready", tags=["system"])
    def ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "data_dir": str(resolved_settings.data_dir),
            "profiles_dir": str(resolved_settings.profiles_dir),
        }

    @app.get("/capabilities", tags=["system"])
    def capabilities() -> dict[str, Any]:
        return {"pipelines": [pipeline.__dict__ for pipeline in list_pipelines()]}

    @app.post("/run", tags=["jobs"])
    def run_task(task: TaskInput) -> dict[str, str]:
        task_id = orchestrator.submit(task)
        executor.submit(orchestrator.run, task_id)
        return {"task_id": task_id, "status": "queued"}

    @app.get("/status/{task_id}", tags=["jobs"])
    def get_status(task_id: str) -> dict[str, Any]:
        try:
            return orchestrator.store.get(task_id).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc

    @app.get("/jobs", tags=["jobs"])
    def list_jobs(status: JobStatus | None = None, content_type: str | None = None, limit: int = 50) -> dict[str, Any]:
        jobs = orchestrator.store.list_jobs(status=status, content_type=content_type, limit=limit)
        return {"jobs": [job.model_dump(mode="json") for job in jobs]}

    @app.get("/jobs/{task_id}/events", tags=["jobs"])
    def get_job_events(task_id: str, limit: int = 50) -> dict[str, Any]:
        events_path = orchestrator.store.events_path(task_id)
        if not events_path.is_file():
            raise HTTPException(status_code=404, detail="task not found")
        events = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                import json

                events.append(json.loads(line))
        return {"task_id": task_id, "events": events[-limit:]}

    return app


app = create_app()
