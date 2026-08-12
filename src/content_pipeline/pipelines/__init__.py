"""Pipeline implementations and registry.

Importing this package triggers ``@register`` decorators on all
built-in pipeline functions, populating the global pipeline registry.
"""

# Import pipeline modules to trigger @register side-effects
from content_pipeline import (  # noqa: F401, E402
    ai_art_pipeline,
    ai_briefing_pipeline,
    finance_pipeline,
    grouped_anime_pipeline,
    japanese_pipeline,
    script_video_pipeline,
    xhs_image_note_pipeline,
)
from content_pipeline.pipelines import anime  # noqa: F401, E402

from .registry import (  # noqa: F401
    PIPELINE_METADATA,
    PIPELINE_REGISTRY,
    PipelineContext,
    PipelineFunc,
    PipelineMeta,
    get_pipeline,
    get_pipeline_meta,
    list_pipelines,
    register,
)
