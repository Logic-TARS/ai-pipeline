from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from content_pipeline.models import (
    AiArtParams,
    AiBriefingParams,
    FinanceParams,
    GroupedAnimeParams,
    JapaneseParams,
    ScriptVideoParams,
    TaskInput,
)
from content_pipeline.pipelines.registry import list_pipelines


class AnimeParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    script: str = Field(min_length=1)
    dry_run: bool = False


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "anime": AnimeParams,
    "finance": FinanceParams,
    "ai_briefing": AiBriefingParams,
    "ai_art": AiArtParams,
    "grouped_anime": GroupedAnimeParams,
    "japanese": JapaneseParams,
    "script_video": ScriptVideoParams,
}

PIPELINE_LABELS = {
    "anime": "动漫短片",
    "finance": "每日金融",
    "ai_briefing": "AI 简报",
    "ai_art": "AI 艺术处理",
    "grouped_anime": "分组动漫",
    "japanese": "日语视觉化",
    "script_video": "口播视频",
}

PIPELINE_ICONS = {
    "anime": "AN",
    "finance": "FN",
    "ai_briefing": "AI",
    "ai_art": "AR",
    "grouped_anime": "GR",
    "japanese": "JP",
    "script_video": "VO",
}


def _field(
    name: str,
    label: str,
    field_type: str = "text",
    *,
    required: bool = False,
    default: Any = None,
    placeholder: str = "",
    help_text: str = "",
    minimum: int | None = None,
    maximum: int | None = None,
    options: list[dict[str, Any]] | None = None,
    rows: int | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "type": field_type,
        "required": required,
        "default": default,
        "placeholder": placeholder,
        "help": help_text,
        "minimum": minimum,
        "maximum": maximum,
        "options": options or [],
        "rows": rows,
    }


PIPELINE_FIELDS: dict[str, list[dict[str, Any]]] = {
    "anime": [
        _field("script", "分镜脚本", "textarea", required=True, placeholder="第一幕……第二幕……", rows=6),
        _field("dry_run", "安全干运行", "checkbox", default=True, help_text="仅生成占位产物，不调用真实工具。"),
    ],
    "finance": [
        _field("source_dir", "Markdown 目录", "path", placeholder="留空时使用 FINANCE_MD_DIR"),
        _field("date", "内容日期", default="auto", placeholder="auto 或 YYYY-MM-DD"),
        _field(
            "script_mode",
            "脚本模式",
            "select",
            default="90_seconds",
            options=[{"value": "90_seconds", "label": "90 秒"}],
        ),
        _field("title", "视频标题", placeholder="留空时自动生成"),
        _field("description", "视频简介", "textarea", default="每日基金日报，仅供参考，不构成投资建议", rows=3),
        _field("tags", "标签", "tags", default=["基金", "A股", "投资"], placeholder="基金, A股, 投资"),
        _field("douyin_account", "抖音账号", default="金融破壁人"),
        _field("kuaishou_account", "快手账号", default="破壁人"),
        _field("dry_run", "安全干运行", "checkbox", default=True),
    ],
    "ai_briefing": [
        _field("source_dir", "简报目录", "path", placeholder="留空时使用 AI_BRIEFING_DIR"),
        _field("date", "内容日期", default="auto", placeholder="auto 或 YYYY-MM-DD"),
        _field(
            "script_mode",
            "脚本模式",
            "select",
            default="90_seconds",
            options=[{"value": "90_seconds", "label": "90 秒"}],
        ),
        _field("handoff_wait_seconds", "交接等待秒数", "number", default=0, minimum=0, maximum=3600),
        _field("title", "视频标题", placeholder="留空时使用简报标题"),
        _field("description", "视频简介", "textarea", default="今日AI简报", rows=3),
        _field("tags", "标签", "tags", default=["AI", "人工智能", "科技"], placeholder="AI, 人工智能, 科技"),
        _field("douyin_account", "抖音账号", default="金融破壁人"),
        _field("kuaishou_account", "快手账号", default="破壁人"),
        _field("tencent_account", "腾讯视频账号"),
        _field("dry_run", "安全干运行", "checkbox", default=True),
        _field("force_regenerate", "强制重新生成", "checkbox", default=False),
    ],
    "ai_art": [
        _field("source_dir", "输入图片目录", "path", required=True, placeholder=r"G:\Job\Photo-Datasets\input"),
        _field("archive_dir", "成功归档目录", "path"),
        _field("failed_dir", "失败归档目录", "path"),
        _field("source_files", "指定文件", "tags", help_text="留空时处理目录顶层全部图片。"),
        _field("image_prompt", "改图提示词", "textarea", required=True, rows=5),
        _field("title", "视频标题", required=True),
        _field("description", "视频简介", "textarea", rows=3),
        _field("tags", "标签", "tags", placeholder="AI绘画, 作品集"),
        _field("group_size", "每组图片数", "number", default=4, minimum=1, maximum=20),
    ],
    "grouped_anime": [
        _field("source_dir", "输入图片目录", "path", required=True, placeholder=r"G:\Job\Photo-Datasets\input"),
        _field("archive_dir", "成功归档目录", "path"),
        _field("failed_dir", "失败归档目录", "path"),
        _field("source_files", "指定文件", "tags", help_text="留空时按文件名前缀扫描目录。"),
        _field("title", "视频标题"),
        _field("description", "视频简介", "textarea", rows=3),
        _field("tags", "标签", "tags", placeholder="动漫, AI视频, 作品集"),
        _field("group_size", "每组图片数", "number", default=4, minimum=1, maximum=20),
        _field("seconds_per_image", "单图秒数", "number", default=5, minimum=1, maximum=60),
    ],
    "japanese": [
        _field("source_dir", "输入图片目录", "path", required=True),
        _field("output_dir", "输出目录", "path", placeholder="留空时写入输入目录/日语改图"),
        _field("source_files", "指定文件", "tags"),
        _field("image_prompt", "附加提示词", "textarea", help_text="通常留空，直接使用日语视觉化 Gem。", rows=3),
        _field("target_gem_url", "目标 Gem URL", "url"),
        _field("dry_run", "安全干运行", "checkbox", default=True),
    ],
    "script_video": [
        _field("title", "视频标题", required=True),
        _field(
            "script",
            "口播稿",
            "textarea",
            required=True,
            help_text="需要 350–500 字；金融内容应包含必要的风险提示。",
            rows=10,
        ),
        _field("description", "视频简介", "textarea", rows=3),
        _field("tags", "标签", "tags", placeholder="AI, 人工智能, 科技"),
        _field("douyin_account", "抖音账号", default="金融破壁人"),
        _field("kuaishou_account", "快手账号", default="破壁人"),
        _field("dry_run", "安全干运行", "checkbox", default=True),
        _field("force_regenerate", "强制重新生成", "checkbox", default=False),
    ],
}


def build_ui_pipelines() -> list[dict[str, Any]]:
    metadata = {item.content_type: item for item in list_pipelines()}
    result = []
    for content_type in PIPELINE_FIELDS:
        meta = metadata.get(content_type)
        if meta is None:
            continue
        result.append(
            {
                "content_type": content_type,
                "label": PIPELINE_LABELS[content_type],
                "icon": PIPELINE_ICONS[content_type],
                "description": meta.description,
                "required_params": meta.required_params,
                "external_tools": meta.external_tools,
                "publish_targets": meta.publish_targets,
                "fields": PIPELINE_FIELDS[content_type],
            }
        )
    return result


def validate_task_for_ui(task: TaskInput) -> tuple[TaskInput, list[str]]:
    content_type = task.content_type
    if content_type not in PARAM_MODELS:
        raise ValueError("请选择受支持的内容流水线")

    params_model = PARAM_MODELS[content_type]
    validated = params_model.model_validate(task.params)
    defaults = validated.model_dump(mode="json", exclude_none=True)
    normalized = task.model_copy(update={"params": {**defaults, **task.params}})

    meta = next((item for item in list_pipelines() if item.content_type == content_type), None)
    if meta is None:
        raise ValueError("所选流水线当前不可用")
    unsupported = sorted({target.platform for target in task.publish_targets} - set(meta.publish_targets))
    if unsupported:
        raise ValueError(f"流水线不支持以下发布平台：{', '.join(unsupported)}")

    warnings: list[str] = []
    if not task.publish and task.publish_targets:
        warnings.append("发布已关闭；发布目标仅作为模板保留，不会调用上传器。")
    if task.publish:
        warnings.append("该任务会在生成和验证后尝试发布，请先使用关闭发布的同类任务审查产物。")
    if task.params.get("dry_run"):
        warnings.append("安全干运行不会调用真实生成或发布工具。")
    return normalized, warnings


def sanitized_error_items(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(str(item) for item in error["loc"] if item != "body"),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in errors
    ]


def sanitized_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return sanitized_error_items(exc.errors())
