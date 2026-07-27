from pathlib import Path

from PIL import Image
import pytest

from content_pipeline.errors import ExternalToolError
from content_pipeline.models import ErrorCode
from content_pipeline.settings import Settings
from content_pipeline.tools import photo_process_client


def test_photo_process_adapter_classifies_gem_redirect_from_failed_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photo_process_dir = tmp_path / "Photo-Process"
    photo_process_dir.mkdir()
    python_path = photo_process_dir / "python.exe"
    main_py = photo_process_dir / "main.py"
    python_path.write_text("", encoding="utf-8")
    main_py.write_text("", encoding="utf-8")
    source = tmp_path / "source.jpg"
    Image.new("RGB", (90, 160), color="blue").save(source)

    def fake_run_command(*_args, **_kwargs):
        raise ExternalToolError(
            'stdout:\n{"success": false, "error": "no image was generated", "error_type": "no_output"}\n'
            "stderr:\n[Gem] 直达 Gem URL 打开后被重定向：https://gemini.google.com/app；"
            "请确认 target_gem_url 是当前账号可访问的 /gem/... 页面"
        )

    monkeypatch.setattr(photo_process_client, "run_command", fake_run_command)

    result = photo_process_client.run_photo_process_adapter(
        source=source,
        prompt="日语视觉化",
        output_path=tmp_path / "out" / "0001.png",
        settings=Settings(
            data_dir=tmp_path / "data",
            profiles_dir=Path("profiles"),
            photo_process_dir=photo_process_dir,
            photo_process_python=python_path,
        ),
        target_gem_name="日语视觉化",
        target_gem_url="https://gemini.google.com/gem/7aaa12067979",
    )

    assert result.ok is False
    assert result.code == ErrorCode.GEM_ACCESS_FAILED
    assert result.raw["photo_process_json"] == {
        "success": False,
        "error": "no image was generated",
        "error_type": "no_output",
    }


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        ("auth_required", ErrorCode.AUTH_REQUIRED),
        ("browser_busy", ErrorCode.BROWSER_BUSY),
        ("ui_changed", ErrorCode.UI_CHANGED),
    ],
)
def test_photo_process_adapter_maps_classified_browser_failures(error_type: str, expected: ErrorCode) -> None:
    assert photo_process_client._error_code_from_payload({"error_type": error_type}) == expected


def test_photo_process_worker_adapter_reuses_local_browser_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.jpg"
    generated = tmp_path / "worker.jpg"
    Image.new("RGB", (90, 160), color="blue").save(source)
    Image.new("RGB", (90, 160), color="green").save(generated)
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return ('{"success": true, "image_path": "' + str(generated).replace("\\", "\\\\") + '"}').encode()

    class FakeOpener:
        def open(self, request, timeout: int):
            captured["url"] = request.full_url
            captured["body"] = request.data
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(photo_process_client, "build_opener", lambda *_args: FakeOpener())
    result = photo_process_client.run_photo_process_adapter(
        source=source,
        prompt="日语视觉化",
        output_path=tmp_path / "out" / "0001.png",
        settings=Settings(photo_process_worker_url="http://127.0.0.1:8000"),
        target_gem_name="日语视觉化",
        target_gem_url="https://gemini.google.com/gem/test",
    )

    assert result.ok is True
    assert result.code == ErrorCode.OK
    assert result.artifacts["processed_path"].endswith("0001.jpg")
    assert captured["url"] == "http://127.0.0.1:8000/api/comic"
    assert b'"target_gem_name": "' in captured["body"]
