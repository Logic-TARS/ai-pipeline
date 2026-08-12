from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ContentType = Literal[
    "anime",
    "finance",
    "ai_briefing",
    "ai_art",
    "xhs_image_note",
    "grouped_anime",
    "japanese",
    "script_video",
    "unknown",
]


class PipelineStep(StrEnum):
    ROUTE = "route"
    SOURCE_SCAN = "source_scan"
    IMAGE = "image"
    VIDEO = "video"
    ARCHIVE = "archive"
    UPLOAD = "upload"
    COMPLETE = "complete"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    PARTIAL = "partial"


class ErrorCode(StrEnum):
    OK = "OK"
    CONFIG_ERROR = "CONFIG_ERROR"
    INPUT_ERROR = "INPUT_ERROR"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_SCAN_FAILED = "SOURCE_SCAN_FAILED"
    EXTERNAL_TOOL_FAILED = "EXTERNAL_TOOL_FAILED"
    NO_OUTPUT = "NO_OUTPUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PRIVATE_VISIBILITY_UNSUPPORTED = "PRIVATE_VISIBILITY_UNSUPPORTED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
    DESKTOP_HELPER_UNAVAILABLE = "DESKTOP_HELPER_UNAVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    BROWSER_BUSY = "BROWSER_BUSY"
    GEM_ACCESS_FAILED = "GEM_ACCESS_FAILED"
    UI_CHANGED = "UI_CHANGED"
    TIMEOUT = "TIMEOUT"


class AdapterResult(BaseModel):
    ok: bool
    tool: str
    code: ErrorCode
    message: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class PublishTarget(BaseModel):
    platform: Literal["douyin", "kuaishou", "bilibili", "tencent", "xiaohongshu"]
    account: str = Field(min_length=1)
    tid: int | None = None

    @model_validator(mode="after")
    def require_bilibili_tid(self) -> PublishTarget:
        if self.platform == "bilibili" and self.tid is None:
            raise ValueError("tid is required for a Bilibili publish target")
        return self


class TaskInput(BaseModel):
    description: str
    content_type: ContentType | None = None
    topic: str | None = None
    publish: bool = False
    publish_targets: list[PublishTarget] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    origin: Literal["content_studio"] | None = None
    source_draft_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    source_draft_revision: int | None = Field(default=None, ge=1)


class DeferredPublishInput(BaseModel):
    publish_targets: list[PublishTarget] = Field(min_length=1, max_length=4)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_publish_fields(self) -> DeferredPublishInput:
        platforms = [target.platform for target in self.publish_targets]
        if len(platforms) != len(set(platforms)):
            raise ValueError("each publish platform can appear only once")
        self.title = self.title.strip()
        self.description = self.description.strip()
        normalized_tags: list[str] = []
        for value in self.tags:
            tag = value.strip().lstrip("#")
            if not tag:
                continue
            if len(tag) > 30:
                raise ValueError("publish tags cannot exceed 30 characters")
            if tag not in normalized_tags:
                normalized_tags.append(tag)
        self.tags = normalized_tags
        return self


PublicationStatus = Literal["queued", "running", "succeeded", "partial", "failed"]


class PublicationAttempt(BaseModel):
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: PublicationStatus = "queued"
    request: DeferredPublishInput
    video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error: str | None = None


class AiArtParams(BaseModel):
    source_dir: Path
    source_files: list[str] = Field(default_factory=list)
    archive_dir: Path | None = None
    failed_dir: Path | None = None
    image_prompt: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    group_size: int = Field(default=4, ge=1, le=20)


class XhsImageNoteParams(BaseModel):
    source_dir: Path
    source_files: list[str] = Field(default_factory=list)
    archive_dir: Path | None = None
    failed_dir: Path | None = None
    image_prompt: str = Field(min_length=1)
    title: str = Field(min_length=1)
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    schedule: str | None = None
    debug: bool = False
    headed: bool = False
    dry_run: bool = False


class JapaneseParams(BaseModel):
    source_dir: Path
    output_dir: Path | None = None
    source_files: list[str] = Field(default_factory=list)
    # The current 日语视觉化 Gem is image-only: upload the image and submit
    # without typing extra prompt text unless a caller explicitly supplies one.
    image_prompt: str = ""
    target_gem_url: str | None = None
    dry_run: bool = False


class GroupedAnimeParams(BaseModel):
    source_dir: Path
    source_files: list[str] = Field(default_factory=list)
    archive_dir: Path | None = None
    failed_dir: Path | None = None
    title: str | None = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    group_size: int = Field(default=4, ge=1, le=20)
    seconds_per_image: int = Field(default=5, ge=1, le=60)


class FinanceParams(BaseModel):
    source_dir: Path | None = None
    date: str = "auto"
    script_mode: Literal["90_seconds"] = "90_seconds"
    douyin_account: str = "金融破壁人"
    kuaishou_account: str = "破壁人"
    title: str | None = None
    description: str = "每日基金日报，仅供参考，不构成投资建议"
    tags: list[str] = Field(default_factory=lambda: ["基金", "A股", "投资"])
    dry_run: bool = False


class AiBriefingParams(BaseModel):
    source_dir: Path | None = None
    date: str = "auto"
    script_mode: Literal["90_seconds"] = "90_seconds"
    handoff_wait_seconds: int = Field(default=600, ge=0, le=3600)
    douyin_account: str = "金融破壁人"
    kuaishou_account: str = "破壁人"
    tencent_account: str | None = None
    title: str | None = None
    description: str = "今日AI简报"
    tags: list[str] = Field(default_factory=lambda: ["AI", "人工智能", "科技"])
    dry_run: bool = False
    force_regenerate: bool = False
    voice_rate: float | None = Field(default=None, ge=0.55, le=1.2)


class ScriptVideoParams(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    script: str = Field(min_length=350, max_length=500)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    douyin_account: str = "金融破壁人"
    kuaishou_account: str = "破壁人"
    dry_run: bool = False
    force_regenerate: bool = False
    voice_rate: float | None = Field(default=None, ge=0.55, le=1.2)


class RouteResult(BaseModel):
    content_type: ContentType
    topic: str
    params: dict[str, Any] = Field(default_factory=dict)


class ImageFileValidation(BaseModel):
    path: Path
    format: str
    width: int
    height: int


class ImageValidation(BaseModel):
    count: int
    files: list[ImageFileValidation]


class VideoValidation(BaseModel):
    duration_seconds: float
    width: int
    height: int
    aspect_ratio: float
    video_codec: str
    audio_codec: str | None = None
    decoded_video_frames: int
    decoded_audio_frames: int


class MediaValidation(BaseModel):
    images: ImageValidation | None = None
    video: VideoValidation | None = None


class JobProgress(BaseModel):
    percent: int = Field(ge=0, le=100)
    phase: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    updated_at: str
    is_estimate: bool = False


class AiArtSourceResult(BaseModel):
    source_path: Path
    processed_path: Path | None = None
    archived_path: Path | None = None
    failed_path: Path | None = None
    adapter_result: AdapterResult | None = None
    error: str | None = None


class AiArtGroupArtifact(BaseModel):
    index: int
    source_images: list[Path] = Field(default_factory=list)
    processed_images: list[Path] = Field(default_factory=list)
    bgm: Path | None = None
    mpt_task_dir: Path | None = None
    video: Path | None = None
    validation: VideoValidation | None = None
    publish_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error: str | None = None


class ArtifactSet(BaseModel):
    images: list[Path] = Field(default_factory=list)
    video: Path | None = None
    upload_result: dict[str, Any] | None = None
    validation: MediaValidation = Field(default_factory=MediaValidation)
    source_results: list[AiArtSourceResult] = Field(default_factory=list)
    groups: list[AiArtGroupArtifact] = Field(default_factory=list)
    source_document: Path | None = None
    narration_script: str | None = None
    script_path: Path | None = None
    subtitle: Path | None = None
    mpt_task_dir: Path | None = None
    handoff_path: Path | None = None
    external_status_path: Path | None = None
    manifest_path: Path | None = None
    publish_results: dict[str, dict[str, Any]] = Field(default_factory=dict)


class JobSnapshot(BaseModel):
    task_id: str
    status: JobStatus
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    store_version: int = 1
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    current_step: PipelineStep | None = None
    progress: JobProgress | None = None
    task: TaskInput
    route: RouteResult | None = None
    artifacts: ArtifactSet = Field(default_factory=ArtifactSet)
    publication_attempts: list[PublicationAttempt] = Field(default_factory=list)
    error: str | None = None


def deferred_publish_fingerprint(task_id: str, video_sha256: str, request: DeferredPublishInput) -> str:
    payload = json.dumps(
        {
            "task_id": task_id,
            "video_sha256": video_sha256,
            "request": request.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def task_fingerprint(task: TaskInput) -> str:
    payload = json.dumps(task.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
