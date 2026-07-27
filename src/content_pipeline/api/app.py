from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException

from content_pipeline.models import TaskInput
from content_pipeline.orchestrator import Orchestrator

app = FastAPI(title="AI Popline Content Pipeline")
orchestrator = Orchestrator()
executor = ThreadPoolExecutor(max_workers=2)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ai-popline"}


@app.post("/run")
def run_task(task: TaskInput) -> dict:
    task_id = orchestrator.submit(task)
    executor.submit(orchestrator.run, task_id)
    return {"task_id": task_id, "status": "queued"}


@app.get("/status/{task_id}")
def get_status(task_id: str) -> dict:
    try:
        return orchestrator.store.get(task_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
