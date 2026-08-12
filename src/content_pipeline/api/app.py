from __future__ import annotations

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path as FilePath
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from content_pipeline.api.artifacts import registered_artifacts
from content_pipeline.api.content import build_content_router
from content_pipeline.api.security import WebSecurity
from content_pipeline.api.ui_schema import (
    build_ui_pipelines,
    sanitized_error_items,
    sanitized_validation_errors,
    validate_task_for_ui,
)
from content_pipeline.content_studio import ContentStudioService
from content_pipeline.deferred_publishing import (
    PublicationEligibilityError,
    publication_readiness,
    publication_summary,
    run_deferred_publication,
    validate_deferred_publish_request,
)
from content_pipeline.job_store import JobDeleteConflictError, utc_now
from content_pipeline.models import (
    DeferredPublishInput,
    JobStatus,
    PipelineStep,
    PublicationAttempt,
    TaskInput,
    deferred_publish_fingerprint,
    task_fingerprint,
)
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.pipelines.registry import list_pipelines
from content_pipeline.settings import Settings, load_settings

WEB_STATIC_DIR = FilePath(__file__).resolve().parents[1] / "web" / "static"


class LoginInput(BaseModel):
    token: str


class DeleteJobsInput(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("task_ids")
    @classmethod
    def validate_task_ids(cls, values: list[str]) -> list[str]:
        if any(len(value) != 32 or any(character not in "0123456789abcdef" for character in value) for value in values):
            raise ValueError("task_ids must contain 32-character lowercase hexadecimal ids")
        return list(dict.fromkeys(values))


class RenameJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be blank")
        return normalized


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application with isolated settings and executor state."""
    resolved_settings = settings or load_settings()
    orchestrator = Orchestrator(settings=resolved_settings)
    executor = ThreadPoolExecutor(max_workers=2)
    security = WebSecurity(resolved_settings)
    content_studio = ContentStudioService(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.orchestrator = orchestrator
        app.state.executor = executor
        app.state.security = security
        app.state.content_studio = content_studio
        try:
            yield
        finally:
            content_studio.shutdown()
            executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="AI Popline Content Pipeline", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.orchestrator = orchestrator
    app.state.executor = executor
    app.state.security = security
    app.state.content_studio = content_studio
    app.include_router(build_content_router(content_studio, orchestrator, executor, resolved_settings))
    app.mount("/static", StaticFiles(directory=WEB_STATIC_DIR), name="static")

    @app.exception_handler(RequestValidationError)
    async def sanitized_request_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "request_validation_failed",
                    "errors": sanitized_error_items(exc.errors()),
                }
            },
        )

    @app.middleware("http")
    async def enforce_web_boundary(request: Request, call_next):
        rejection = security.enforce(request)
        if rejection is not None:
            return security.add_security_headers(request, rejection)
        response = await call_next(request)
        return security.add_security_headers(request, response)

    @app.get("/", include_in_schema=False)
    def web_console() -> FileResponse:
        return FileResponse(WEB_STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    def ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "data_dir_available": resolved_settings.data_dir.is_dir(),
            "profiles_available": resolved_settings.profiles_dir.is_dir(),
        }

    @app.post("/auth/login", tags=["authentication"])
    def login(credentials: LoginInput, request: Request) -> JSONResponse:
        if not resolved_settings.web_auth_required:
            raise HTTPException(status_code=404, detail="authentication is not enabled")
        if len(resolved_settings.web_session_secret.get_secret_value()) < 32:
            raise HTTPException(status_code=503, detail="session authentication is not configured")
        peer = request.client.host if request.client else "unknown"
        if not security.verify_login(peer, credentials.token):
            raise HTTPException(status_code=401, detail="invalid credentials")
        cookie, session = security.new_session()
        response = JSONResponse({"authenticated": True, "csrf_token": session.csrf_token})
        security.set_session_cookies(response, cookie, session, secure=request.url.scheme == "https")
        return response

    @app.post("/auth/logout", tags=["authentication"])
    def logout() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        security.clear_session_cookies(response)
        return response

    @app.get("/auth/me", tags=["authentication"])
    def current_user(request: Request) -> dict[str, Any]:
        return {"authenticated": True, "method": request.state.auth_kind}

    @app.get("/capabilities", tags=["system"])
    def capabilities() -> dict[str, Any]:
        return {"pipelines": [pipeline.__dict__ for pipeline in list_pipelines()]}

    @app.get("/ui/bootstrap", tags=["web"])
    def ui_bootstrap() -> dict[str, Any]:
        return {
            "app_name": "AI Popline",
            "api_contract_version": 2,
            "features": {
                "content_draft_crud": True,
                "content_draft_bulk_delete": True,
                "job_rename": True,
                "job_delete": True,
                "job_bulk_delete": True,
            },
            "auth_required": resolved_settings.web_auth_required,
            "publish_enabled": resolved_settings.web_publish_enabled,
            "active_refresh_ms": 2500,
            "idle_refresh_ms": 15000,
            "statuses": [status.value for status in JobStatus],
            "steps": [step.value for step in PipelineStep],
            "pipelines": build_ui_pipelines(resolved_settings),
        }

    @app.post("/validate-task", tags=["jobs"])
    def validate_task(task: TaskInput) -> dict[str, Any]:
        if task.publish and not resolved_settings.web_publish_enabled:
            raise HTTPException(status_code=403, detail="web publishing is disabled")
        try:
            normalized, warnings = validate_task_for_ui(task)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "task_validation_failed", "errors": sanitized_validation_errors(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "task_validation_failed", "errors": [{"field": "task", "message": str(exc)}]},
            ) from exc
        return {
            "valid": True,
            "task": normalized.model_dump(mode="json"),
            "task_fingerprint": task_fingerprint(normalized),
            "warnings": warnings,
        }

    @app.post("/run", tags=["jobs"])
    def run_task(
        task: TaskInput,
        request: Request,
        publish_confirmation: str | None = Header(default=None, alias="X-AI-Popline-Publish-Confirmation"),
    ) -> dict[str, str]:
        if task.publish:
            if not resolved_settings.web_publish_enabled:
                raise HTTPException(status_code=403, detail="web publishing is disabled")
            fingerprint = task_fingerprint(task)
            expected = f"PUBLISH:{fingerprint}"
            if not publish_confirmation or not secrets.compare_digest(publish_confirmation, expected):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "publish_confirmation_required",
                        "task_fingerprint": fingerprint,
                        "required_confirmation": expected,
                    },
                )
            if not security.session_is_recent(request):
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "recent_authentication_required",
                        "message": "recent authentication required for publishing",
                    },
                )
        task_id = orchestrator.submit(task)
        executor.submit(orchestrator.run, task_id)
        return {"task_id": task_id, "status": "queued"}

    @app.get("/status/{task_id}", tags=["jobs"])
    def get_status(task_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            snapshot = orchestrator.store.get(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return snapshot.model_dump(mode="json") | {"publication_summary": publication_summary(snapshot)}

    @app.get("/jobs", tags=["jobs"])
    def list_jobs(status: JobStatus | None = None, content_type: str | None = None, limit: int = 50) -> dict[str, Any]:
        jobs = orchestrator.store.list_jobs(status=status, content_type=content_type, limit=max(1, min(limit, 200)))
        return {
            "jobs": [job.model_dump(mode="json") | {"publication_summary": publication_summary(job)} for job in jobs]
        }

    def delete_jobs_result(request: DeleteJobsInput) -> dict[str, list[str]]:
        return orchestrator.store.delete_jobs(request.task_ids)

    app.add_api_route("/jobs/batch-delete", delete_jobs_result, methods=["POST"], tags=["jobs"])
    app.add_api_route("/jobs/delete", delete_jobs_result, methods=["POST"], tags=["jobs"], include_in_schema=False)

    @app.get("/jobs/{task_id}", tags=["jobs"])
    def get_job(task_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            snapshot = orchestrator.store.get(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return snapshot.model_dump(mode="json") | {"publication_summary": publication_summary(snapshot)}

    @app.patch("/jobs/{task_id}", tags=["jobs"])
    def rename_job(request: RenameJobInput, task_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            snapshot = orchestrator.store.rename_job(task_id, request.display_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return snapshot.model_dump(mode="json") | {"publication_summary": publication_summary(snapshot)}

    @app.delete("/jobs/{task_id}", tags=["jobs"])
    def delete_job(task_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            orchestrator.store.delete_job(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        except JobDeleteConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"task_id": task_id, "deleted": True}

    @app.get("/jobs/{task_id}/publish-readiness", tags=["publishing"])
    def get_publish_readiness(task_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            snapshot = orchestrator.store.get(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        return {
            "task_id": task_id,
            **publication_readiness(
                snapshot,
                orchestrator.store,
                publish_enabled=resolved_settings.web_publish_enabled,
            ),
            "publication_summary": publication_summary(snapshot),
        }

    @app.post("/jobs/{task_id}/publish", tags=["publishing"], status_code=202)
    def publish_completed_job(
        publication: DeferredPublishInput,
        request: Request,
        task_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        publish_confirmation: str | None = Header(default=None, alias="X-AI-Popline-Publish-Confirmation"),
    ) -> dict[str, str]:
        if not resolved_settings.web_publish_enabled:
            raise HTTPException(status_code=403, detail="web publishing is disabled")
        try:
            snapshot = orchestrator.store.get(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        try:
            _video, video_sha256 = validate_deferred_publish_request(
                snapshot,
                orchestrator.store,
                publication,
                publish_enabled=True,
            )
        except PublicationEligibilityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        fingerprint = deferred_publish_fingerprint(task_id, video_sha256, publication)
        expected = f"PUBLISH:{fingerprint}"
        if not publish_confirmation or not secrets.compare_digest(publish_confirmation, expected):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "publish_confirmation_required",
                    "publication_fingerprint": fingerprint,
                    "required_confirmation": expected,
                },
            )
        if not security.session_is_recent(request):
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "recent_authentication_required",
                    "message": "recent authentication required for publishing",
                },
            )

        attempt = PublicationAttempt(
            attempt_id=uuid4().hex,
            request=publication,
            video_sha256=video_sha256,
            requested_at=utc_now(),
        )
        try:
            orchestrator.store.add_publication_attempt(task_id, attempt)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        executor.submit(
            run_deferred_publication,
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            store=orchestrator.store,
            settings=resolved_settings,
        )
        return {"task_id": task_id, "attempt_id": attempt.attempt_id, "status": "queued"}

    @app.get("/jobs/{task_id}/events", tags=["jobs"])
    def get_job_events(task_id: str = Path(pattern=r"^[0-9a-f]{32}$"), limit: int = 50) -> dict[str, Any]:
        events_path = orchestrator.store.events_path(task_id)
        if not events_path.is_file():
            raise HTTPException(status_code=404, detail="task not found")
        events = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return {"task_id": task_id, "events": events[-max(1, min(limit, 500)) :]}

    @app.get("/jobs/{task_id}/artifacts", tags=["artifacts"])
    def list_job_artifacts(task_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> dict[str, Any]:
        try:
            snapshot = orchestrator.store.get(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        artifacts = registered_artifacts(snapshot, orchestrator.store.job_dir(task_id))
        return {
            "task_id": task_id,
            "artifacts": [
                {
                    "artifact_id": artifact.artifact_id,
                    "name": artifact.path.name,
                    "relative_path": artifact.relative_path,
                    "media_type": artifact.media_type,
                    "size": artifact.size,
                    "url": f"/jobs/{task_id}/artifacts/{artifact.artifact_id}",
                }
                for artifact in artifacts.values()
            ],
        }

    @app.get("/jobs/{task_id}/artifacts/{artifact_id}", tags=["artifacts"])
    def get_job_artifact(
        task_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        artifact_id: str = Path(pattern=r"^[0-9a-f]{24}$"),
    ) -> FileResponse:
        try:
            snapshot = orchestrator.store.get(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        artifact = registered_artifacts(snapshot, orchestrator.store.job_dir(task_id)).get(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(
            artifact.path,
            media_type=artifact.media_type,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(artifact.path.name)}"},
        )

    return app


app = create_app()
