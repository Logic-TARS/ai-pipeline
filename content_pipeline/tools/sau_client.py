from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from content_pipeline.errors import ConfigError, ExternalToolError, PrivateVisibilityUnsupported
from content_pipeline.models import PublishTarget
from content_pipeline.profiles import UploadProfile
from content_pipeline.rendering import render_template
from content_pipeline.settings import Settings
from content_pipeline.tools.common import run_command


def _bilibili_private_args(settings: Settings) -> list[str]:
    private_args = shlex.split(settings.sau_bilibili_private_args)
    for index, item in enumerate(private_args):
        if item == "--is-only-self" and index + 1 < len(private_args) and private_args[index + 1] == "1":
            return private_args
        if item == "--is-only-self=1":
            return private_args
    raise PrivateVisibilityUnsupported(
        "Bilibili private upload requires SAU_BILIBILI_PRIVATE_ARGS='--is-only-self 1'."
    )


def _already_published_result(error: ExternalToolError) -> dict[str, Any] | None:
    text = str(error)
    if "此内容已在" not in text or "小时内发布过" not in text:
        return None
    return {
        "success": True,
        "skipped": True,
        "reason": "already_published",
        "visibility": "private",
        "private_visibility_proof": "enforced_by_uploader_before_recorded_success",
        "publication_proof": "publish_history_dedup",
    }


def _tencent_short_title(title: str) -> str:
    normalized = re.sub(r"[-_,，、]+", " ", title)
    normalized = re.sub(
        r"[^0-9A-Za-z\u4e00-\u9fff 《》“”‘’\"':：+？?%℃]",
        "",
        normalized,
    )
    return re.sub(r"\s+", " ", normalized).strip()[:16] or "视频草稿"


def call_sau_target(
    *,
    target: PublishTarget,
    video: Path,
    title: str,
    desc: str,
    tags: list[str],
    settings: Settings,
    dry_run: bool = False,
) -> dict[str, Any]:
    if target.platform == "douyin":
        command = [
            str(settings.sau_exe),
            "douyin",
            "upload-video",
            "--account",
            target.account,
            "--file",
            str(video.resolve()),
            "--title",
            title[:30],
            "--desc",
            desc,
            "--headless",
        ]
        if tags:
            command.extend(["--tags", ",".join(tags)])
        if dry_run:
            return {"success": True, "dry_run": True, "command": command, "visibility": "private"}
        try:
            result = run_command(command, cwd=settings.sau_dir, timeout=1800, retries=0)
        except ExternalToolError as exc:
            already_published = _already_published_result(exc)
            if already_published:
                return already_published
            raise
        output = "\n".join((result.stdout, result.stderr))
        if "已设置为“仅自己可见”" not in output or "视频发布成功" not in output:
            raise PrivateVisibilityUnsupported(
                "Douyin upload did not provide proof of private visibility and successful publication."
            )
        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "visibility": "private",
            "private_visibility_proof": "已设置为“仅自己可见”",
            "publication_proof": "视频发布成功",
        }

    if target.platform == "kuaishou":
        command = [
            str(settings.sau_exe),
            "kuaishou",
            "upload-video",
            "--account",
            target.account,
            "--file",
            str(video.resolve()),
            "--title",
            title[:30],
            "--desc",
            desc,
            "--headed",
            "--debug",
        ]
        if tags:
            command.extend(["--tags", ",".join(tags)])
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "command": command,
                "visibility": "private",
                "private_visibility_check": "skipped_in_dry_run",
            }
        try:
            result = run_command(command, cwd=settings.sau_dir, timeout=1800, retries=0)
        except ExternalToolError as exc:
            already_published = _already_published_result(exc)
            if already_published:
                return already_published
            raise
        output = "\n".join((result.stdout, result.stderr))
        if "已设置为“仅自己可见”" not in output or "视频发布成功" not in output:
            raise PrivateVisibilityUnsupported(
                "Kuaishou upload did not provide proof of private visibility and successful publication."
            )
        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "visibility": "private",
            "private_visibility_proof": "已设置为“仅自己可见”",
            "publication_proof": "视频发布成功",
        }

    if target.platform == "tencent":
        command = [
            str(settings.sau_exe),
            "tencent",
            "upload-video",
            "--account",
            target.account,
            "--file",
            str(video.resolve()),
            "--title",
            title[:30],
            "--short-title",
            _tencent_short_title(title),
            "--desc",
            desc,
            "--draft",
            "--headed",
            "--debug",
        ]
        if tags:
            command.extend(["--tags", ",".join(tags)])
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "command": command,
                "delivery_status": "draft",
                "visibility": "draft",
                "draft_proof": "skipped_in_dry_run",
            }
        result = run_command(command, cwd=settings.sau_dir, timeout=1800, retries=0)
        output = "\n".join((result.stdout, result.stderr))
        if "视频草稿保存成功" not in output:
            raise PrivateVisibilityUnsupported(
                "Tencent upload did not provide proof that the video was saved as a draft."
            )
        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "delivery_status": "draft",
            "visibility": "draft",
            "draft_proof": "视频草稿保存成功",
        }

    if target.platform == "bilibili":
        command = [
            str(settings.sau_exe),
            "bilibili",
            "upload-video",
            "--account",
            target.account,
            "--file",
            str(video.resolve()),
            "--title",
            title[:80],
            "--desc",
            desc,
            "--tid",
            str(target.tid),
        ]
        if tags:
            command.extend(["--tags", ",".join(tags)])
        if dry_run:
            return {"success": True, "dry_run": True, "command": command, "visibility": "private"}
        private_args = _bilibili_private_args(settings)
        command.extend(private_args)
        result = run_command(command, cwd=settings.sau_dir, timeout=1800, retries=2)
        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "visibility": "private",
            "private_visibility_proof": "biliup --is-only-self 1",
            "publication_proof": "biliup exited successfully",
        }
    raise ConfigError(f"unsupported upload platform: {target.platform}")


def call_sau_upload(
    *,
    profile: UploadProfile,
    topic: str,
    params: dict[str, Any],
    video: Path,
    settings: Settings,
) -> dict[str, Any]:
    if profile.platform != "bilibili":
        raise ConfigError(f"unsupported upload platform: {profile.platform}")
    if profile.visibility != "private":
        raise ConfigError("only private upload visibility is allowed")

    title = render_template(profile.title_template, topic, params)
    desc = render_template(profile.desc_template, topic, params)
    command = [
        str(settings.sau_exe),
        "bilibili",
        "upload-video",
        "--account",
        profile.account,
        "--file",
        str(video),
        "--title",
        title,
        "--desc",
        desc,
        "--tid",
        str(profile.tid),
    ]
    if profile.tags:
        command.extend(["--tags", ",".join(profile.tags)])
    if profile.schedule:
        command.extend(["--schedule", profile.schedule])
    if params.get("dry_run"):
        return {
            "success": True,
            "dry_run": True,
            "command": command,
            "visibility": "private",
            "private_visibility_check": "skipped_in_dry_run",
        }

    private_args = _bilibili_private_args(settings)
    command.extend(private_args)

    result = run_command(command, cwd=settings.sau_dir, timeout=1800, retries=2)
    return {
        "success": True,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "visibility": "private",
        "private_visibility_proof": "biliup --is-only-self 1",
        "publication_proof": "biliup exited successfully",
    }
