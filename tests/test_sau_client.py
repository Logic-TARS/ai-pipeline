from pathlib import Path

import pytest

from content_pipeline.errors import ExternalToolError, PrivateVisibilityUnsupportedError
from content_pipeline.models import PublishTarget
from content_pipeline.profiles import UploadProfile
from content_pipeline.settings import Settings
from content_pipeline.tools.sau_client import call_sau_target, call_sau_upload


def test_douyin_target_dry_run_is_private(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    result = call_sau_target(
        target=PublishTarget(platform="douyin", account="山下富士"),
        video=video,
        title="title",
        desc="desc",
        tags=["AI绘画"],
        settings=Settings(),
        dry_run=True,
    )
    assert result["visibility"] == "private"
    assert "--headless" in result["command"]


def test_kuaishou_target_dry_run_is_private_and_headed(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    result = call_sau_target(
        target=PublishTarget(platform="kuaishou", account="破壁人"),
        video=video,
        title="title",
        desc="desc",
        tags=["基金"],
        settings=Settings(),
        dry_run=True,
    )
    assert result["visibility"] == "private"
    assert "--headed" in result["command"]
    assert "--force" not in result["command"]
    file_arg = result["command"][result["command"].index("--file") + 1]
    assert Path(file_arg).is_absolute()


def test_kuaishou_requires_private_and_success_proof(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")

    def fake_run_command(command, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(args=command, returncode=0, stdout="视频发布成功", stderr="")

    monkeypatch.setattr("content_pipeline.tools.sau_client.run_command", fake_run_command)
    with pytest.raises(PrivateVisibilityUnsupportedError, match="Kuaishou"):
        call_sau_target(
            target=PublishTarget(platform="kuaishou", account="破壁人"),
            video=video,
            title="title",
            desc="desc",
            tags=["基金"],
            settings=Settings(),
        )


def test_publish_history_duplicate_is_idempotent_success(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")

    def fake_run_command(command, **kwargs):
        raise ExternalToolError("[douyin/金融破壁人] 此内容已在 24 小时内发布过，或上次点击发布后状态未知。")

    monkeypatch.setattr("content_pipeline.tools.sau_client.run_command", fake_run_command)
    result = call_sau_target(
        target=PublishTarget(platform="douyin", account="金融破壁人"),
        video=video,
        title="title",
        desc="desc",
        tags=["基金"],
        settings=Settings(),
    )
    assert result["success"] is True
    assert result["reason"] == "already_published"
    assert result["publication_proof"] == "publish_history_dedup"


def test_bilibili_target_requires_tid() -> None:
    with pytest.raises(ValueError, match="tid"):
        PublishTarget(platform="bilibili", account="default")


def test_tencent_target_dry_run_is_draft_only(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    result = call_sau_target(
        target=PublishTarget(platform="tencent", account="破壁人Wallbreaker"),
        video=video,
        title="视频号验收标题超过十六个字符",
        desc="只保存草稿",
        tags=["AI", "测试"],
        settings=Settings(),
        dry_run=True,
    )

    command = result["command"]
    assert result["delivery_status"] == "draft"
    assert result["visibility"] == "draft"
    assert "--draft" in command
    assert "--headed" in command
    assert "--debug" in command
    assert "--force" not in command
    assert "--schedule" not in command
    assert Path(command[command.index("--file") + 1]).is_absolute()
    short_title = command[command.index("--short-title") + 1]
    assert "-" not in short_title
    assert len(short_title) <= 16


def test_tencent_target_requires_draft_success_proof(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")

    def fake_run_command(command, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(args=command, returncode=0, stdout="saved", stderr="")

    monkeypatch.setattr("content_pipeline.tools.sau_client.run_command", fake_run_command)
    with pytest.raises(PrivateVisibilityUnsupportedError, match="Tencent"):
        call_sau_target(
            target=PublishTarget(platform="tencent", account="破壁人Wallbreaker"),
            video=video,
            title="title",
            desc="desc",
            tags=[],
            settings=Settings(),
        )


def test_tencent_target_returns_draft_delivery_status(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")

    def fake_run_command(command, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="🥳 视频草稿保存成功\nTencent/WeChat Channels video draft saved",
            stderr="",
        )

    monkeypatch.setattr("content_pipeline.tools.sau_client.run_command", fake_run_command)
    result = call_sau_target(
        target=PublishTarget(platform="tencent", account="破壁人Wallbreaker"),
        video=video,
        title="title",
        desc="desc",
        tags=[],
        settings=Settings(),
    )
    assert result["delivery_status"] == "draft"
    assert result["visibility"] == "draft"
    assert result["draft_proof"] == "视频草稿保存成功"


def test_dry_run_upload_does_not_require_private_args(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    result = call_sau_upload(
        profile=UploadProfile(account="default", tid=249, visibility="private"),
        topic="topic",
        params={"dry_run": True},
        video=video,
        settings=Settings(),
    )
    assert result["dry_run"] is True
    assert result["visibility"] == "private"


def test_real_upload_requires_private_args(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    captured_command = None

    def fake_run_command(command, **kwargs):
        nonlocal captured_command
        captured_command = command
        import subprocess

        return subprocess.CompletedProcess(args=command, returncode=0, stdout="uploaded", stderr="")

    monkeypatch.setattr("content_pipeline.tools.sau_client.run_command", fake_run_command)

    with pytest.raises(PrivateVisibilityUnsupportedError, match="--is-only-self 1"):
        call_sau_upload(
            profile=UploadProfile(account="default", tid=249, visibility="private"),
            topic="topic",
            params={},
            video=video,
            settings=Settings(sau_bilibili_private_args=""),
        )
    assert captured_command is None


def test_real_bilibili_upload_passes_verified_private_flag(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    captured_command = None

    def fake_run_command(command, **kwargs):
        nonlocal captured_command
        captured_command = command
        import subprocess

        return subprocess.CompletedProcess(args=command, returncode=0, stdout="uploaded", stderr="")

    monkeypatch.setattr("content_pipeline.tools.sau_client.run_command", fake_run_command)
    result = call_sau_target(
        target=PublishTarget(platform="bilibili", account="酸菜鱼-sakana", tid=27),
        video=video,
        title="title",
        desc="desc",
        tags=["动漫"],
        settings=Settings(sau_bilibili_private_args="--is-only-self 1"),
    )

    assert captured_command[-2:] == ["--is-only-self", "1"]
    assert result["visibility"] == "private"
    assert result["private_visibility_proof"] == "biliup --is-only-self 1"
