from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from content_pipeline.job_store import JobStore
from content_pipeline.models import DeferredPublishInput, JobSnapshot
from content_pipeline.settings import Settings
from content_pipeline.tools.sau_client import call_sau_target

SUPPORTED_SCRIPT_VIDEO_TARGETS = ("douyin", "kuaishou")
ACTIVE_PUBLICATION_STATUSES = {"queued", "running"}
PUBLICATION_STATE_LABELS = {
    "waiting_generation": "待生成",
    "not_published": "未发布",
    "publishing": "发布中",
    "published": "已发布",
    "partial": "部分发布",
    "failed": "发布失败",
    "not_applicable": "不适用",
}


class PublicationEligibilityError(ValueError):
    """Raised when a completed job cannot safely reuse its generated video."""


def is_content_studio_job(snapshot: JobSnapshot) -> bool:
    """Recognize current jobs and legacy content-studio jobs created before provenance fields existed."""
    return snapshot.task.origin == "content_studio" or (
        snapshot.task.description.startswith("内容工作台 · ")
        and (snapshot.route.content_type if snapshot.route else snapshot.task.content_type) == "script_video"
    )


def publication_summary(snapshot: JobSnapshot) -> dict[str, Any]:
    """Return an evidence-based publication state without changing generation status."""
    content_studio_job = is_content_studio_job(snapshot)
    if not content_studio_job:
        return {
            "state": "not_applicable",
            "label": PUBLICATION_STATE_LABELS["not_applicable"],
            "message": "该任务不使用内容工作台的独立发布流程。",
            "content_studio_job": False,
            "active": False,
            "has_published": False,
            "needs_attention": False,
            "latest_attempt_id": None,
            "latest_attempt_status": None,
            "completed_at": None,
            "targets": [],
            "published_targets": [],
        }

    attempts = snapshot.publication_attempts
    successful_targets: dict[tuple[str, str], dict[str, Any]] = {}
    for attempt in attempts:
        requested = {target.platform: target for target in attempt.request.publish_targets}
        for platform, result in attempt.results.items():
            if result.get("success") is not True:
                continue
            target = requested.get(platform)
            account = target.account if target else ""
            successful_targets[(platform, account)] = _publication_target_summary(
                platform=platform,
                account=account,
                attempt_status=attempt.status,
                result=result,
            )

    if not attempts:
        waiting = snapshot.status in {"queued", "running"}
        generated = snapshot.status in {"succeeded", "partial"}
        state = "waiting_generation" if waiting else "not_published"
        if waiting:
            message = "视频仍在生成，尚未发送到任何自媒体账号。"
        elif generated:
            message = "仅完成视频生成，尚未发送到任何自媒体账号。"
        else:
            message = "视频生成未成功，未发送到任何自媒体账号。"
        return {
            "state": state,
            "label": PUBLICATION_STATE_LABELS[state],
            "message": message,
            "content_studio_job": True,
            "active": False,
            "has_published": False,
            "needs_attention": False,
            "latest_attempt_id": None,
            "latest_attempt_status": None,
            "completed_at": None,
            "targets": [],
            "published_targets": [],
        }

    latest = attempts[-1]
    result_by_platform = latest.results
    targets = [
        _publication_target_summary(
            platform=target.platform,
            account=target.account,
            attempt_status=latest.status,
            result=result_by_platform.get(target.platform),
        )
        for target in latest.request.publish_targets
    ]
    has_published = bool(successful_targets)
    if latest.status in ACTIVE_PUBLICATION_STATUSES:
        state = "publishing"
        message = "正在向所选自媒体账号发布，请等待平台返回结果。"
    elif latest.status == "succeeded":
        state = "published"
        message = "平台已返回发布成功凭证。"
    elif latest.status == "partial" or has_published:
        state = "partial"
        message = (
            "已有账号发布成功，但最近一次发布仍有失败目标。"
            if latest.status == "failed"
            else "部分账号已发布成功，仍有目标发布失败。"
        )
    else:
        state = "failed"
        message = "未收到任何账号的发布成功凭证。"

    return {
        "state": state,
        "label": PUBLICATION_STATE_LABELS[state],
        "message": message,
        "content_studio_job": True,
        "active": latest.status in ACTIVE_PUBLICATION_STATUSES,
        "has_published": has_published,
        "needs_attention": state in {"partial", "failed"},
        "latest_attempt_id": latest.attempt_id,
        "latest_attempt_status": latest.status,
        "completed_at": latest.finished_at,
        "targets": targets,
        "published_targets": list(successful_targets.values()),
    }


def _publication_target_summary(
    *,
    platform: str,
    account: str,
    attempt_status: str,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    if result is None:
        status = "publishing" if attempt_status in ACTIVE_PUBLICATION_STATUSES else "failed"
        success = False
        visibility = None
        proof = None
        error = None if status == "publishing" else "平台未返回发布结果"
        skipped = False
    else:
        success = result.get("success") is True
        skipped = bool(result.get("skipped"))
        status = "published" if success else "failed"
        visibility = result.get("delivery_status") or result.get("visibility")
        proof = result.get("publication_proof") or result.get("draft_proof") or result.get("private_visibility_proof")
        error = result.get("error")
    return {
        "platform": platform,
        "account": account,
        "status": status,
        "success": success,
        "visibility": visibility,
        "proof": proof,
        "error": error,
        "skipped": skipped,
    }


def publication_readiness(snapshot: JobSnapshot, store: JobStore, *, publish_enabled: bool) -> dict[str, Any]:
    reasons: list[str] = []
    content_type = snapshot.route.content_type if snapshot.route else snapshot.task.content_type
    params = snapshot.route.params if snapshot.route else snapshot.task.params

    if not publish_enabled:
        reasons.append("服务端 Web 发布当前安全关闭。")
    if not is_content_studio_job(snapshot):
        reasons.append("仅内容工作台生成的口播视频支持任务中心发布。")
    if content_type != "script_video":
        reasons.append("该任务不是可延迟发布的口播视频。")
    if snapshot.status not in {"succeeded", "partial"}:
        reasons.append("视频生成任务尚未成功完成。")
    if bool(params.get("dry_run")):
        reasons.append("安全干运行产物不能发布。")
    if snapshot.artifacts.validation.video is None:
        reasons.append("视频尚未通过媒体校验。")
    if any(item.status in ACTIVE_PUBLICATION_STATUSES for item in snapshot.publication_attempts):
        reasons.append("已有发布操作正在排队或运行。")

    try:
        video = resolve_guarded_video(snapshot, store)
    except PublicationEligibilityError as exc:
        reasons.append(str(exc))
        video = None

    return {
        "eligible": not reasons,
        "content_studio_job": is_content_studio_job(snapshot),
        "reasons": reasons,
        "publish_enabled": publish_enabled,
        "supported_platforms": list(SUPPORTED_SCRIPT_VIDEO_TARGETS),
        "defaults": {
            "title": str(params.get("title") or snapshot.task.topic or snapshot.task.description),
            "description": str(params.get("description") or ""),
            "tags": list(params.get("tags") or []),
            "accounts": {
                "douyin": str(params.get("douyin_account") or "金融破壁人"),
                "kuaishou": str(params.get("kuaishou_account") or "破壁人"),
            },
        },
        "video_ready": video is not None,
    }


def validate_deferred_publish_request(
    snapshot: JobSnapshot,
    store: JobStore,
    request: DeferredPublishInput,
    *,
    publish_enabled: bool,
) -> tuple[Path, str]:
    readiness = publication_readiness(snapshot, store, publish_enabled=publish_enabled)
    if not readiness["eligible"]:
        raise PublicationEligibilityError("; ".join(readiness["reasons"]))
    unsupported = sorted({target.platform for target in request.publish_targets} - set(SUPPORTED_SCRIPT_VIDEO_TARGETS))
    if unsupported:
        raise PublicationEligibilityError(f"口播视频不支持以下发布平台：{', '.join(unsupported)}")
    video = resolve_guarded_video(snapshot, store)
    return video, sha256_file(video)


def resolve_guarded_video(snapshot: JobSnapshot, store: JobStore) -> Path:
    video = snapshot.artifacts.video
    if video is None:
        raise PublicationEligibilityError("任务没有可发布的视频产物。")
    resolved = video.resolve()
    job_dir = store.job_dir(snapshot.task_id).resolve()
    try:
        resolved.relative_to(job_dir)
    except ValueError as exc:
        raise PublicationEligibilityError("视频产物不在受保护的任务目录内。") from exc
    if not resolved.is_file():
        raise PublicationEligibilityError("视频产物不存在或已被移除。")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_deferred_publication(
    *,
    task_id: str,
    attempt_id: str,
    store: JobStore,
    settings: Settings,
) -> None:
    """Publish an already validated artifact without changing its generation job lifecycle."""
    try:
        attempt = store.mark_publication_started(task_id, attempt_id)
        snapshot = store.get(task_id)
        video = resolve_guarded_video(snapshot, store)
        if sha256_file(video) != attempt.video_sha256:
            raise PublicationEligibilityError("视频产物在发布确认后发生变化，已拒绝发布。")

        for target in attempt.request.publish_targets:
            try:
                result = call_sau_target(
                    target=target,
                    video=video,
                    title=attempt.request.title,
                    desc=attempt.request.description,
                    tags=attempt.request.tags,
                    settings=settings,
                    dry_run=False,
                )
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            store.set_publication_target_result(task_id, attempt_id, target.platform, result)

        completed = store.get(task_id)
        current = next(item for item in completed.publication_attempts if item.attempt_id == attempt_id)
        successes = [result.get("success") is True for result in current.results.values()]
        if successes and all(successes):
            status = "succeeded"
            error = None
        elif any(successes):
            status = "partial"
            error = "部分发布目标失败"
        else:
            status = "failed"
            error = "所有发布目标均失败"
        store.finish_publication_attempt(task_id, attempt_id, status, error)
    except Exception as exc:
        store.finish_publication_attempt(task_id, attempt_id, "failed", str(exc))
