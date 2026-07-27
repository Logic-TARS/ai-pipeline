from __future__ import annotations

import hashlib
from pathlib import Path

from .models import ArtifactSet
from .tools.slideshow_client import SLIDESHOW_RENDER_VERSION


def _group_title(title: str, index: int, total: int) -> str:
    """Append a group counter to a title, e.g. 'My Title 1/3'."""
    return f"{title} {index}/{total}"


def _group_signature(images: list[Path]) -> str:
    """Compute a short deterministic hash from image paths and sizes."""
    value = "|".join(
        [SLIDESHOW_RENDER_VERSION]
        + [f"{path.resolve()}:{path.stat().st_size}" for path in images]
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _partial_reasons(artifacts: ArtifactSet, publishing_requested: bool) -> list[str]:
    """Collect human-readable reasons why a job finished as PARTIAL."""
    reasons: list[str] = []
    failed_sources = sum(1 for record in artifacts.source_results if record.error)
    failed_groups = sum(1 for group in artifacts.groups if group.error)
    if failed_sources:
        reasons.append(f"{failed_sources} source image(s) failed")
    if failed_groups:
        reasons.append(f"{failed_groups} video group(s) failed")
    if publishing_requested:
        failed_publications = sum(
            1
            for group in artifacts.groups
            for result in group.publish_results.values()
            if result.get("status") != "succeeded"
        )
        if failed_publications:
            reasons.append(f"{failed_publications} publication(s) did not succeed")
    return reasons
