from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from content_pipeline.models import (
    AiArtParams,
    AiBriefingParams,
    FinanceParams,
    GroupedAnimeParams,
    JapaneseParams,
    ScriptVideoParams,
    TaskInput,
    XhsImageNoteParams,
)

__all__ = ["AnimeParams", "PARAM_MODELS", "validate_task_params"]


class AnimeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = Field(min_length=1, max_length=4000)
    dry_run: bool = False


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "anime": AnimeParams,
    "finance": FinanceParams,
    "ai_briefing": AiBriefingParams,
    "ai_art": AiArtParams,
    "xhs_image_note": XhsImageNoteParams,
    "grouped_anime": GroupedAnimeParams,
    "japanese": JapaneseParams,
    "script_video": ScriptVideoParams,
}


def validate_task_params(task: TaskInput) -> TaskInput:
    content_type = task.content_type
    if content_type not in PARAM_MODELS:
        raise ValueError("请选择受支持的内容流水线")

    params_model = PARAM_MODELS[content_type]
    validated = params_model.model_validate(task.params)
    defaults = validated.model_dump(mode="json", exclude_none=True)
    return task.model_copy(update={"params": {**defaults, **task.params}})
