"""External tool adapters."""

from content_pipeline.adapters.gemini import GeminiMcpClient, call_gemini_skill, generate_many
from content_pipeline.adapters.mpt import (
    FinanceMptResult,
    NarratedMptResult,
    call_finance_mpt,
    call_mpt,
    call_narrated_mpt,
)
from content_pipeline.adapters.photo_process import (
    SOURCE_IMAGE_SUFFIXES,
    archive_source,
    photo_process_contract,
    run_photo_process_adapter,
    scan_source_images,
)
from content_pipeline.adapters.sau import call_sau_target, call_sau_upload

__all__ = [
    "FinanceMptResult",
    "GeminiMcpClient",
    "NarratedMptResult",
    "SOURCE_IMAGE_SUFFIXES",
    "archive_source",
    "call_finance_mpt",
    "call_gemini_skill",
    "generate_many",
    "call_mpt",
    "call_narrated_mpt",
    "call_sau_target",
    "call_sau_upload",
    "photo_process_contract",
    "run_photo_process_adapter",
    "scan_source_images",
]
