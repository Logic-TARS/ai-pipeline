import shutil
from pathlib import Path

from PIL import Image

from content_pipeline import japanese_pipeline
from content_pipeline.job_store import JobStore
from content_pipeline.models import AdapterResult, ErrorCode, JobStatus, TaskInput
from content_pipeline.orchestrator import Orchestrator
from content_pipeline.settings import Settings


def test_japanese_pipeline_saves_processed_images_locally(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "japanese"
    source_dir.mkdir()
    for name in ("1.png", "2.png"):
        Image.new("RGB", (90, 160), color="blue").save(source_dir / name)

    def fake_photo_process(
        *,
        source: Path,
        output_path: Path,
        target_gem_name: str,
        target_gem_url: str,
        **_kwargs,
    ) -> AdapterResult:
        assert source.parent.name == "photo_process_sources"
        assert target_gem_name == "日语视觉化"
        assert target_gem_url == "https://gemini.google.com/gem/f306c82a8105"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path)},
            evidence={"validation": {"count": 1}},
        )

    monkeypatch.setattr(japanese_pipeline, "run_photo_process_adapter", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
                "process_name": "日语视觉化",
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
    assert snapshot.artifacts.source_results[0].adapter_result is not None
    assert snapshot.artifacts.source_results[0].adapter_result.code == ErrorCode.OK


def test_japanese_pipeline_partial_when_one_image_fails(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("1.png", "2.png", "3.png"):
        Image.new("RGB", (90, 160), color="blue").save(source_dir / name)

    def fake_photo_process(
        *,
        source: Path,
        output_path: Path,
        target_gem_name: str,
        target_gem_url: str,
        **_kwargs,
    ) -> AdapterResult:
        assert target_gem_name == "日语视觉化"
        assert target_gem_url == "https://gemini.google.com/gem/f306c82a8105"
        if source.name == "0002.png":
            return AdapterResult(
                ok=False,
                tool="Photo-Process",
                code=ErrorCode.EXTERNAL_TOOL_FAILED,
                message="image rejected",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path)},
            evidence={"validation": {"count": 1}},
        )

    monkeypatch.setattr(japanese_pipeline, "run_photo_process_adapter", fake_photo_process)

    settings = Settings(
        data_dir=tmp_path / "output",
        profiles_dir=Path("profiles"),
        pipeline_defaults_file=tmp_path / "missing-defaults.yaml",
    )
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "process_name": "日语视觉化",
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.PARTIAL
    assert len(snapshot.artifacts.images) == 2
    assert snapshot.artifacts.source_results[1].error == "image rejected"
    assert snapshot.artifacts.source_results[1].adapter_result is not None
    assert snapshot.artifacts.source_results[1].adapter_result.code == ErrorCode.EXTERNAL_TOOL_FAILED
    assert len(list((source_dir / "日语改图").glob("*.png"))) == 2
    assert len(list(source_dir.glob("*.png"))) == 3


def test_japanese_pipeline_retries_by_name_when_fixed_gem_url_fails(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "japanese"
    source_dir.mkdir()
    Image.new("RGB", (90, 160), color="blue").save(source_dir / "1.png")
    calls: list[str | None] = []

    def fake_photo_process(
        *,
        source: Path,
        output_path: Path,
        target_gem_name: str,
        target_gem_url: str | None,
        **_kwargs,
    ) -> AdapterResult:
        assert target_gem_name == "日语视觉化"
        calls.append(target_gem_url)
        if len(calls) == 1:
            return AdapterResult(
                ok=False,
                tool="Photo-Process",
                code=ErrorCode.GEM_ACCESS_FAILED,
                message="Gem URL redirected to /app",
            )
        assert target_gem_url is None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path)},
            evidence={"validation": {"count": 1}},
        )

    monkeypatch.setattr(japanese_pipeline, "run_photo_process_adapter", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
                "process_name": "日语视觉化",
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert calls == ["https://gemini.google.com/gem/f306c82a8105", None]
    assert snapshot.artifacts.source_results[0].adapter_result is not None
    assert snapshot.artifacts.source_results[0].adapter_result.code == ErrorCode.OK


def test_japanese_pipeline_defaults_to_image_only_prompt(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "japanese"
    source_dir.mkdir()
    Image.new("RGB", (90, 160), color="blue").save(source_dir / "1.png")
    prompts: list[str] = []

    def fake_photo_process(
        *,
        source: Path,
        prompt: str,
        output_path: Path,
        target_gem_name: str,
        target_gem_url: str,
        **_kwargs,
    ) -> AdapterResult:
        prompts.append(prompt)
        assert target_gem_name == "日语视觉化"
        assert target_gem_url == "https://gemini.google.com/gem/f306c82a8105"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path)},
            evidence={"validation": {"count": 1}},
        )

    monkeypatch.setattr(japanese_pipeline, "run_photo_process_adapter", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert prompts == [""]


def test_japanese_pipeline_uses_task_target_gem_url(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "japanese"
    source_dir.mkdir()
    Image.new("RGB", (90, 160), color="blue").save(source_dir / "1.png")
    target_url = "https://gemini.google.com/gem/f306c82a8105"

    def fake_photo_process(
        *,
        source: Path,
        output_path: Path,
        target_gem_name: str,
        target_gem_url: str,
        **_kwargs,
    ) -> AdapterResult:
        assert target_gem_name == "日语视觉化"
        assert target_gem_url == target_url
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return AdapterResult(
            ok=True,
            tool="Photo-Process",
            code=ErrorCode.OK,
            artifacts={"processed_path": str(output_path)},
            evidence={"validation": {"count": 1}},
        )

    monkeypatch.setattr(japanese_pipeline, "run_photo_process_adapter", fake_photo_process)

    settings = Settings(data_dir=tmp_path / "output", profiles_dir=Path("profiles"))
    orchestrator = Orchestrator(settings=settings, store=JobStore(settings.data_dir))
    task_id = orchestrator.submit(
        TaskInput(
            description="日语图片改图",
            content_type="japanese",
            params={
                "source_dir": str(source_dir),
                "output_dir": str(output_dir),
                "process_name": "日语视觉化",
                "target_gem_url": target_url,
            },
        )
    )
    orchestrator.run(task_id)
    snapshot = orchestrator.store.get(task_id)

    assert snapshot.status == JobStatus.SUCCEEDED
    assert snapshot.artifacts.source_results[0].adapter_result is not None
    assert snapshot.artifacts.source_results[0].adapter_result.code == ErrorCode.OK
