"""Group images by filename prefix (text before trailing digits)."""

import re
from pathlib import Path


def _natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def group_by_prefix(images: list[Path]) -> dict[str, list[Path]]:
    """Group images by the text prefix before trailing digits in the filename.

    Uses regex ^(.*?)(\\d+)$ to extract the prefix. Images without trailing
    digits each become their own group keyed by the full filename.

    Args:
        images: List of Path objects representing image files.

    Returns:
        Dict mapping prefix key to a list of Paths sorted by natural order.
        Groups are sorted alphabetically by prefix key.
    """
    if not images:
        return {}

    prefix_pattern = re.compile(r"^(.*?)(\d+)$")
    groups: dict[str, list[Path]] = {}

    for path in images:
        match = prefix_pattern.match(path.stem)
        if match:
            key = match.group(1)
        else:
            key = path.name
        groups.setdefault(key, []).append(path)

    return {
        key: sorted(group, key=_natural_key)
        for key, group in sorted(groups.items())
    }
