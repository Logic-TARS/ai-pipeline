from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ContentDraft",
    "CreateDraftInput",
    "DraftRevisionInput",
    "DraftStatus",
    "GenerateVideoInput",
    "ResearchSource",
    "SourceStatus",
    "UpdateDraftInput",
]

DraftStatus = Literal["collecting", "ready", "partial", "failed"]
SourceStatus = Literal["pending", "succeeded", "failed"]


def normalize_required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name}不能为空")
    return normalized


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    skill_id: str = Field(min_length=1, max_length=120)
    status: SourceStatus = "pending"
    fetched_at: str | None = Field(default=None, max_length=80)
    data_as_of: str | None = Field(default=None, max_length=80)
    summary: str = Field(default="", max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=2000)

    @field_validator("source_id", "label", "skill_id")
    @classmethod
    def normalize_required_fields(cls, value: str) -> str:
        return normalize_required_text(value, "研究来源字段")

    @field_validator("fetched_at", "data_as_of", "error")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        return value.strip()


def normalize_focus_assets(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        if len(normalized) > 32:
            raise ValueError("关注股票名称或代码不能超过 32 个字符")
        if normalized not in result:
            result.append(normalized)
    return result


def normalize_source_ids(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        source_id = value.strip()
        if not source_id:
            continue
        if len(source_id) > 80 or not source_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("资料源 ID 只能包含字母、数字、横线或下划线")
        if source_id not in result:
            result.append(source_id)
    return result


class ContentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    template_id: Literal["finance_90s", "ai_briefing_90s"]
    title: str = Field(min_length=1, max_length=120)
    focus_assets: list[str] = Field(default_factory=list, max_length=5)
    enabled_source_ids: list[str] | None = Field(default=None, max_length=20)
    script: str = Field(default="", max_length=1200)
    status: DraftStatus = "collecting"
    revision: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=utc_now, max_length=80)
    updated_at: str = Field(default_factory=utc_now, max_length=80)
    research: list[ResearchSource] = Field(default_factory=list, max_length=20)
    research_error: str | None = Field(default=None, max_length=2000)
    script_generation: dict[str, Any] | None = None
    video_task_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return normalize_required_text(value, "标题")

    @field_validator("script")
    @classmethod
    def normalize_script(cls, value: str) -> str:
        return value.strip()

    @field_validator("research_error")
    @classmethod
    def normalize_research_error(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("focus_assets")
    @classmethod
    def validate_focus_assets(cls, values: list[str]) -> list[str]:
        return normalize_focus_assets(values)

    @field_validator("enabled_source_ids")
    @classmethod
    def validate_enabled_source_ids(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else normalize_source_ids(values)

    @field_validator("video_task_ids")
    @classmethod
    def validate_video_task_ids(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            task_id = value.strip()
            if len(task_id) != 32 or any(character not in "0123456789abcdef" for character in task_id):
                raise ValueError("video_task_ids must contain 32-character lowercase hexadecimal ids")
            if task_id not in result:
                result.append(task_id)
        return result


class CreateDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: Literal["finance_90s", "ai_briefing_90s"] = "finance_90s"
    title: str = Field(default="今日金融资讯", min_length=1, max_length=120)
    focus_assets: list[str] = Field(default_factory=list, max_length=5)
    enabled_source_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        return normalize_required_text(value, "标题")

    @field_validator("focus_assets")
    @classmethod
    def validate_focus_assets(cls, values: list[str]) -> list[str]:
        return normalize_focus_assets(values)

    @field_validator("enabled_source_ids")
    @classmethod
    def validate_enabled_source_ids(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else normalize_source_ids(values)


class UpdateDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    script: str = Field(max_length=1200)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        return normalize_required_text(value, "标题")

    @field_validator("script")
    @classmethod
    def script_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("口播稿不能为空")
        return value


class DraftRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    enabled_source_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("enabled_source_ids")
    @classmethod
    def validate_enabled_source_ids(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else normalize_source_ids(values)


class GenerateVideoInput(DraftRevisionInput):
    dry_run: bool = False
    voice_rate: float | None = Field(default=None, ge=0.55, le=1.2)
