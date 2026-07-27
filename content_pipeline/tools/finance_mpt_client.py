from __future__ import annotations

from pathlib import Path

from content_pipeline.settings import Settings
from content_pipeline.tools.narrated_mpt_client import (
    NarratedMptResult,
    call_narrated_mpt,
    looks_like_file_reference,
    validate_spoken_subtitle,
)


FinanceMptResult = NarratedMptResult


def call_finance_mpt(
    *,
    publication_date: str,
    title: str,
    script: str,
    output_dir: Path,
    settings: Settings,
    dry_run: bool = False,
) -> FinanceMptResult:
    return call_narrated_mpt(
        task_name=f"finance-{publication_date.replace('-', '')}",
        title=title,
        script=script,
        output_dir=output_dir,
        settings=settings,
        dry_run=dry_run,
        voice_rate=1.0,
    )
