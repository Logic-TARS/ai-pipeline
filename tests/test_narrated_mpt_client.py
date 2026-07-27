from __future__ import annotations

import json
import subprocess
from pathlib import Path

from content_pipeline.settings import Settings
from content_pipeline.tools.narrated_mpt_client import _briefing_voice_rate, call_narrated_mpt


def test_mismatched_input_hash_never_reuses_existing_task(tmp_path: Path, monkeypatch) -> None:
    mpt_dir = tmp_path / "mpt"
    task_dir = mpt_dir / "storage" / "tasks" / "ai-briefing-20260720"
    task_dir.mkdir(parents=True)
    (task_dir / "final-1.mp4").write_bytes(b"old-video")
    (task_dir / "subtitle.srt").write_text("old subtitle", encoding="utf-8")
    (task_dir / "script.json").write_text(json.dumps({"script": "new narration"}), encoding="utf-8")
    (task_dir / "ai-popline-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": "ai-briefing-20260720",
                "title": "Daily AI",
                "script_sha256": "wrong",
                "input_sha256": {"article.md": "old"},
            }
        ),
        encoding="utf-8",
    )
    captured: list[str] = []
    captured_kwargs: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.extend(command)
        captured_kwargs.update(kwargs)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "final-1.mp4").write_bytes(b"new-video")
        (task_dir / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:05,000\n这是一段足够长并且有效的人工智能简报字幕。\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("content_pipeline.tools.narrated_mpt_client.run_command", fake_run)
    result = call_narrated_mpt(
        task_name="ai-briefing-20260720",
        title="Daily AI",
        script="new narration",
        output_dir=tmp_path / "output",
        settings=Settings(mpt_dir=mpt_dir, mpt_python=Path("python")),
        input_hashes={"article.md": "new"},
    )
    assert captured[captured.index("--task-id") + 1] == "ai-briefing-20260720"
    assert captured_kwargs["env"] == {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    assert captured_kwargs["timeout"] == 3600
    assert result.video.read_bytes() == b"new-video"
    assert list((mpt_dir / "storage" / "tasks").glob("ai-briefing-20260720.stale-*"))


def test_invalid_exact_task_is_archived_instead_of_reused(tmp_path: Path, monkeypatch) -> None:
    mpt_dir = tmp_path / "mpt"
    task_dir = mpt_dir / "storage" / "tasks" / "finance-20260721"
    task_dir.mkdir(parents=True)
    (task_dir / "final-1.mp4").write_bytes(b"incomplete-video")
    (task_dir / "subtitle.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\n这是一段足够长并且有效的金融字幕。\n",
        encoding="utf-8",
    )
    (task_dir / "script.json").write_text(json.dumps({"script": "same narration"}), encoding="utf-8")
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "final-1.mp4").write_bytes(b"regenerated-video")
        (task_dir / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:05,000\n这是一段足够长并且有效的金融字幕。\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("content_pipeline.tools.narrated_mpt_client.run_command", fake_run)
    result = call_narrated_mpt(
        task_name="finance-20260721",
        title="每日基金日报",
        script="same narration",
        output_dir=tmp_path / "output",
        settings=Settings(mpt_dir=mpt_dir, mpt_python=Path("python")),
    )
    assert captured
    assert result.video.read_bytes() == b"regenerated-video"
    assert list((mpt_dir / "storage" / "tasks").glob("finance-20260721.stale-*"))


def test_briefing_voice_rate_targets_ninety_seconds() -> None:
    assert _briefing_voice_rate("x" * 482) == 0.82
    assert 0.55 <= _briefing_voice_rate("x" * 350) <= 1.0
    assert 0.55 <= _briefing_voice_rate("x" * 500) <= 1.0
