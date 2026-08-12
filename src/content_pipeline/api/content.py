from __future__ import annotations

from concurrent.futures import Executor
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

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
from content_pipeline.settings import Settings


class DeleteDraftsInput(BaseModel):
    draft_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("draft_ids")
    @classmethod
    def validate_draft_ids(cls, values: list[str]) -> list[str]:
        if any(len(value) != 32 or any(character not in "0123456789abcdef" for character in value) for value in values):
            raise ValueError("draft_ids must contain 32-character lowercase hexadecimal ids")
        return list(dict.fromkeys(values))


def build_content_router(
    service: ContentStudioService,
    orchestrator: Orchestrator,
    job_executor: Executor,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/content", tags=["content-studio"])

    @router.get("/bootstrap")
    def content_bootstrap() -> dict[str, Any]:
        return {**service.bootstrap(), "publish_enabled": settings.web_publish_enabled}

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

    def delete_drafts_result(request: DeleteDraftsInput) -> dict[str, list[str]]:
        return service.delete_many(request.draft_ids)

    router.add_api_route("/drafts/batch-delete", delete_drafts_result, methods=["POST"])
    router.add_api_route("/drafts/delete", delete_drafts_result, methods=["POST"], include_in_schema=False)

    @router.get("/drafts/{draft_id}")
    def get_draft(draft_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            return service.store.get(draft_id).model_dump(mode="json")
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc

    @router.delete("/drafts/{draft_id}")
    def delete_draft(draft_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            service.delete(draft_id)
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc
        except DraftConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"draft_id": draft_id, "deleted": True}

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
            draft = service.prepare_for_video(draft_id, request.revision)
        except DraftNotFoundError as exc:
            raise HTTPException(status_code=404, detail="content draft not found") from exc
        except DraftConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        errors = service.validate_for_video(draft)
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "content_script_validation_failed",
                    "errors": [{"field": "script", "message": message} for message in errors],
                },
            )
        params: dict[str, Any] = {"title": draft.title, "script": draft.script, "dry_run": request.dry_run}
        if request.voice_rate is not None:
            params["voice_rate"] = request.voice_rate
        task = TaskInput(
            description=f"内容工作台 · {draft.title}",
            content_type="script_video",
            topic=draft.title,
            publish=False,
            publish_targets=[],
            params=params,
            origin="content_studio",
            source_draft_id=draft.draft_id,
            source_draft_revision=draft.revision,
        )
        task_id = orchestrator.submit(task)
        try:
            service.register_video_task(draft_id, draft.revision, task_id)
        except DraftConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        job_executor.submit(orchestrator.run, task_id)
        return {"task_id": task_id, "status": "queued", "draft_id": draft_id}

    return router
