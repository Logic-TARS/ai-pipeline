"""Publishing safety policy — fail-closed rules for each platform.

All publishing defaults to OFF. Every platform must prove private/limited
visibility before an upload is considered successful. Any uncertainty
results in a BLOCKED status.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformPolicy:
    platform: str
    visibility_requirement: str
    proof_required: str
    fail_closed_rule: str


# ---------------------------------------------------------------------------
# Platform policies
# ---------------------------------------------------------------------------

DOUYIN = PlatformPolicy(
    platform="douyin",
    visibility_requirement="仅自己可见 (self-only visible)",
    proof_required="SAU stdout must contain evidence of private visibility setting",
    fail_closed_rule="If '仅自己可见' is not confirmed in upload output, the target reports PUBLISH_FAILED.",
)

KUAISHOU = PlatformPolicy(
    platform="kuaishou",
    visibility_requirement="仅自己可见 (self-only visible)",
    proof_required="SAU stdout must contain evidence of private visibility setting",
    fail_closed_rule="If private visibility is not confirmed, the target reports PUBLISH_FAILED.",
)

BILIBILI = PlatformPolicy(
    platform="bilibili",
    visibility_requirement="--is-only-self 1",
    proof_required="SAU_BILIBILI_PRIVATE_ARGS must be configured and passed to the upload command",
    fail_closed_rule=(
        "Bilibili upload is BLOCKED entirely if SAU_BILIBILI_PRIVATE_ARGS is not configured. "
        "A configured but failed upload reports PUBLISH_FAILED."
    ),
)

TENCENT = PlatformPolicy(
    platform="tencent",
    visibility_requirement="Save as draft only (never auto-publish)",
    proof_required="SAU must confirm draft was saved, not published",
    fail_closed_rule="If draft status is not confirmed, the target reports PUBLISH_FAILED.",
)

PLATFORM_POLICIES: dict[str, PlatformPolicy] = {p.platform: p for p in [DOUYIN, KUAISHOU, BILIBILI, TENCENT]}


def get_policy(platform: str) -> PlatformPolicy:
    """Return the publishing policy for *platform*."""
    return PLATFORM_POLICIES[platform]


def validate_publish_request(platform: str, publish_enabled: bool, private_args_configured: bool) -> list[str]:
    """Return a list of blocking reasons. Empty list means the publish can proceed."""
    blockers: list[str] = []

    if not publish_enabled:
        blockers.append("publish is not enabled on this task")
        return blockers

    policy = get_policy(platform)

    if platform == "bilibili" and not private_args_configured:
        blockers.append(f"Bilibili requires SAU_BILIBILI_PRIVATE_ARGS: {policy.fail_closed_rule}")

    return blockers
