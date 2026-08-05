from __future__ import annotations

from concurrent.futures import Executor
from typing import Any

from fastapi import APIRouter, HTTPException, Path

from content_pipeline.content_studio.models import (
    CreateDraftInput,
    DraftRevisionInput,
    GenerateVideoInput,
    UpdateDraftInput,
)
from content_pipeline.content_studio.service import ContentStudioService
from content_pipeline.content_studio.store import DraftConflictError, DraftNotFoundError
from content_pipeline.models import TaskInput
from content_pipeline.orchestrator import Orchestrator


def build_content_router(
    service: ContentStudioService,
    orchestrator: Orchestrator,
    job_executor: Executor,
) -> APIRouter:
    router = APIRouter(prefix="/content", tags=["content-studio"])

    @router.get("/bootstrap")
    def content_bootstrap() -> dict[str, Any]:
        return service.bootstrap()

    @router.get("/drafts")
    def list_drafts(limit: int = 30) -> dict[str, Any]:
        drafts = service.store.list(limit=max(1, min(limit, 100)))
        return {
            "drafts": [
                draft.model_dump(mode="json", exclude={"research"})
                | {
                    "source_counts": {
                        "total": len(draft.research),
                        "succeeded": sum(item.status == "succeeded" for item in draft.research),
                        "failed": sum(item.status == "failed" for item in draft.research),
                    }
                }
                for draft in drafts
            ]
        }

    @router.post("/drafts", status_code=202)
    def create_draft(request: CreateDraftInput) -> dict[str, Any]:
        return service.create(request).model_dump(mode="json")

    @router.get("/drafts/{draft_id}")
    def get_draft(draft_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            return service.store.get(draft_id).model_dump(mode="json")
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc

    @router.patch("/drafts/{draft_id}")
    def update_draft(
        request: UpdateDraftInput,
        draft_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> dict[str, Any]:
        try:
            draft = service.update(
                draft_id,
                revision=request.revision,
                title=request.title,
                script=request.script,
            )
            return draft.model_dump(mode="json")
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc
        except DraftConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/drafts/{draft_id}/refresh", status_code=202)
    def refresh_draft(
        request: DraftRevisionInput,
        draft_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> dict[str, Any]:
        try:
            return service.refresh(draft_id, request.revision).model_dump(mode="json")
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc
        except DraftConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/drafts/{draft_id}/video", status_code=202)
    def generate_video(
        request: GenerateVideoInput,
        draft_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> dict[str, Any]:
        try:
            draft = service.store.get(draft_id)
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc
        if draft.revision != request.revision:
            raise HTTPException(status_code=409, detail="content draft changed; save the latest version first")
        errors = service.validate_for_video(draft)
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "content_script_validation_failed",
                    "errors": [{"field": "script", "message": message} for message in errors],
                },
            )
        task = TaskInput(
            description=f"内容工作台 · {draft.title}",
            content_type="script_video",
            topic=draft.title,
            publish=False,
            params={"title": draft.title, "script": draft.script, "dry_run": request.dry_run},
        )
        task_id = orchestrator.submit(task)
        try:
            service.register_video_task(draft_id, request.revision, task_id)
        except DraftConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        job_executor.submit(orchestrator.run, task_id)
        return {"task_id": task_id, "status": "queued", "draft_id": draft_id}

    return router
