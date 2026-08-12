from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DraftStatus = Literal["collecting", "ready", "partial", "failed"]
SourceStatus = Literal["pending", "succeeded", "failed"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ResearchSource(BaseModel):
    source_id: str
    label: str
    skill_id: str
    status: SourceStatus = "pending"
    fetched_at: str | None = None
    data_as_of: str | None = None
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ContentDraft(BaseModel):
    draft_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    template_id: str
    title: str = Field(min_length=1, max_length=120)
    focus_assets: list[str] = Field(default_factory=list, max_length=5)
    script: str = Field(default="", max_length=1200)
    status: DraftStatus = "collecting"
    revision: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    research: list[ResearchSource] = Field(default_factory=list)
    research_error: str | None = None
    video_task_ids: list[str] = Field(default_factory=list)

    @field_validator("focus_assets")
    @classmethod
    def validate_focus_assets(cls, values: list[str]) -> list[str]:
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


class CreateDraftInput(BaseModel):
    template_id: Literal["finance_90s", "ai_briefing_90s"] = "finance_90s"
    title: str = Field(default="今日金融资讯", min_length=1, max_length=120)
    focus_assets: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()


class UpdateDraftInput(BaseModel):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    script: str = Field(max_length=1200)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()


class DraftRevisionInput(BaseModel):
    revision: int = Field(ge=1)


class GenerateVideoInput(DraftRevisionInput):
    dry_run: bool = False
    voice_rate: float | None = Field(default=None, ge=0.55, le=1.2)
