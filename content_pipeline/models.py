from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


ContentType = Literal["anime", "finance", "ai_briefing", "ai_art", "grouped_anime", "japanese", "unknown"]


class PipelineStep(str, Enum):
    ROUTE = "route"
    SOURCE_SCAN = "source_scan"
    IMAGE = "image"
    VIDEO = "video"
    ARCHIVE = "archive"
    UPLOAD = "upload"
    COMPLETE = "complete"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    PARTIAL = "partial"


class ErrorCode(str, Enum):
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
    platform: Literal["douyin", "kuaishou", "bilibili", "tencent"]
    account: str = Field(min_length=1)
    tid: int | None = None

    @model_validator(mode="after")
    def require_bilibili_tid(self) -> "PublishTarget":
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


class JapaneseParams(BaseModel):
    source_dir: Path
    output_dir: Path | None = None
    source_files: list[str] = Field(default_factory=list)
    image_prompt: str = Field(min_length=1)
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
    current_step: PipelineStep | None = None
    task: TaskInput
    route: RouteResult | None = None
    artifacts: ArtifactSet = Field(default_factory=ArtifactSet)
    error: str | None = None
