import os
from pathlib import Path

import pytest

from content_pipeline.deliverables import export_deliverables


def test_export_deliverables_keeps_canonical_file_and_writes_metadata(tmp_path: Path) -> None:
    data_dir = tmp_path / "output"
    job_dir = data_dir / "jobs" / ("a" * 32)
    video = job_dir / "video" / "final.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")

    delivery_dir, files, metadata = export_deliverables(
        data_dir=data_dir,
        job_dir=job_dir,
        pipeline="ai_briefing",
        key="20261103",
        files={"briefing.mp4": video},
        title="标题",
        description="描述",
        tags=["AI", "#科技"],
    )

    delivered_video = delivery_dir / "briefing.mp4"
    assert delivered_video.read_bytes() == b"video"
    assert video.is_file()
    assert metadata == job_dir / "publish_metadata.txt"
    assert metadata.read_text(encoding="utf-8") == "标题：\n标题\n\n描述：\n描述\n\n标签：\n#AI #科技\n"
    assert set(files) == {delivered_video, delivery_dir / "publish_metadata.txt"}
    if os.name == "nt":
        assert delivered_video.stat().st_ino == video.stat().st_ino


def test_export_deliverables_rejects_files_outside_job(tmp_path: Path) -> None:
    data_dir = tmp_path / "output"
    job_dir = data_dir / "jobs" / ("a" * 32)
    job_dir.mkdir(parents=True)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")

    with pytest.raises(ValueError, match="inside the job directory"):
        export_deliverables(
            data_dir=data_dir,
            job_dir=job_dir,
            pipeline="finance",
            key="20261103",
            files={"video.mp4": outside},
        )
