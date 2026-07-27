import shutil
from pathlib import Path

from PIL import Image

from content_pipeline import japanese_pipeline
from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


def test_japanese_pipeline_saves_processed_images_locally(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "japanese"
    source_dir.mkdir()
    for name in ("1.png", "2.png"):
        Image.new("RGB", (90, 160), color="blue").save(source_dir / name)

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return output_path

    monkeypatch.setattr(japanese_pipeline, "call_photo_process", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
                "image_prompt": "改成日语风格海报",
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert [path.name for path in snapshot.artifacts.images] == ["0001.png", "0002.png"]
    assert len(list(output_dir.glob("*.png"))) == 2
    assert len(list(source_dir.glob("*.png"))) == 2
    assert snapshot.artifacts.video is None
    assert snapshot.artifacts.groups == []
    assert snapshot.artifacts.upload_result == {"skipped": True, "reason": "local_image_pipeline"}


def test_japanese_pipeline_partial_when_one_image_fails(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("1.png", "2.png", "3.png"):
        Image.new("RGB", (90, 160), color="blue").save(source_dir / name)

    def fake_photo_process(*, source: Path, output_path: Path, **_kwargs) -> Path:
        if source.name == "2.png":
            raise RuntimeError("image rejected")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return output_path

    monkeypatch.setattr(japanese_pipeline, "call_photo_process", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "image_prompt": "改成日语风格海报",
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.PARTIAL
    assert len(snapshot.artifacts.images) == 2
    assert snapshot.artifacts.source_results[1].error == "image rejected"
    assert len(list((source_dir / "日语改图").glob("*.png"))) == 2
    assert len(list(source_dir.glob("*.png"))) == 3
