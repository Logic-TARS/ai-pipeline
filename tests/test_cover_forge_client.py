from __future__ import annotations

import io
import json
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from content_pipeline.models import CoverParams, ErrorCode
from content_pipeline.settings import Settings
from content_pipeline.tools import cover_forge_client
from content_pipeline.tools.cover_forge_client import run_cover_forge_adapter

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"generated-cover"


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "image/png", status: int = 200):
        self.body = body
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


class FakeOpener:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        if self.error is not None:
            raise self.error
        return self.response


def _settings() -> Settings:
    return Settings(_env_file=None, cover_forge_url="http://127.0.0.1:3000", cover_forge_timeout_seconds=12)


def test_cover_forge_success_builds_contract_bypasses_proxy_and_writes_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = FakeOpener(FakeResponse(PNG_BYTES))
    handlers = []

    def fake_build_opener(handler):
        handlers.append(handler)
        return opener

    monkeypatch.setattr(cover_forge_client, "build_opener", fake_build_opener)
    output = tmp_path / "cover" / "cover.png"
    result = run_cover_forge_adapter(
        params=CoverParams(
            title="测试封面",
            size="portrait",
            template="ai-poster",
            title_position="center",
            background_scale=1.25,
            background_position_x=20,
            background_position_y=80,
        ),
        output_path=output,
        settings=_settings(),
    )

    assert result.ok is True
    assert result.code == ErrorCode.OK
    assert result.artifacts == {"cover_path": str(output)}
    assert output.read_bytes() == PNG_BYTES
    assert list(output.parent.glob("*.tmp")) == []
    assert handlers[0].proxies == {}
    assert opener.timeout == 12
    assert opener.request.full_url == "http://127.0.0.1:3000/api/covers"
    assert opener.request.get_method() == "POST"
    assert json.loads(opener.request.data) == {
        "title": "测试封面",
        "size": "portrait",
        "template": "ai-poster",
        "titlePosition": "center",
        "backgroundTransform": {"scale": 1.25, "positionX": 20.0, "positionY": 80.0},
    }


def test_cover_forge_encodes_valid_background_as_data_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    background = tmp_path / "background.webp"
    background.write_bytes(b"RIFF\x08\x00\x00\x00WEBPdata")
    opener = FakeOpener(FakeResponse(PNG_BYTES))
    monkeypatch.setattr(cover_forge_client, "build_opener", lambda _handler: opener)

    result = run_cover_forge_adapter(
        params=CoverParams(title="背景测试", background_image=background),
        output_path=tmp_path / "cover.png",
        settings=_settings(),
    )

    assert result.ok is True
    payload = json.loads(opener.request.data)
    assert payload["backgroundImage"].startswith("data:image/webp;base64,")
    assert "backgroundImage" not in result.raw
    assert "backgroundImage" not in result.evidence


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("background.gif", b"GIF89a", "must be PNG, JPEG, or WebP"),
        ("background.png", b"not-png", "does not match image/png"),
    ],
)
def test_cover_forge_rejects_invalid_background_inputs(tmp_path: Path, name: str, body: bytes, message: str) -> None:
    background = tmp_path / name
    background.write_bytes(body)

    result = run_cover_forge_adapter(
        params=CoverParams(title="背景测试", background_image=background),
        output_path=tmp_path / "cover.png",
        settings=_settings(),
    )

    assert result.ok is False
    assert result.code == ErrorCode.INPUT_ERROR
    assert message in (result.message or "")


def test_cover_forge_rejects_background_over_five_mib(tmp_path: Path) -> None:
    background = tmp_path / "background.png"
    background.write_bytes(PNG_BYTES + b"x" * (5 * 1024 * 1024))

    result = run_cover_forge_adapter(
        params=CoverParams(title="背景测试", background_image=background),
        output_path=tmp_path / "cover.png",
        settings=_settings(),
    )

    assert result.code == ErrorCode.INPUT_ERROR
    assert "5 MiB" in (result.message or "")


def test_cover_forge_maps_structured_http_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"error": {"code": "INVALID_TITLE", "message": "标题无法排版"}}).encode()
    error = HTTPError(
        "http://127.0.0.1:3000/api/covers",
        400,
        "Bad Request",
        Message(),
        io.BytesIO(body),
    )
    monkeypatch.setattr(cover_forge_client, "build_opener", lambda _handler: FakeOpener(error=error))

    result = run_cover_forge_adapter(
        params=CoverParams(title="错误测试"),
        output_path=tmp_path / "cover.png",
        settings=_settings(),
    )

    assert result.ok is False
    assert result.code == ErrorCode.INPUT_ERROR
    assert result.message == "标题无法排版"
    assert result.raw["cover_forge_error"] == {
        "http_status": 400,
        "code": "INVALID_TITLE",
        "message": "标题无法排版",
    }


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (URLError(ConnectionRefusedError("connection refused")), ErrorCode.EXTERNAL_TOOL_FAILED),
        (URLError(TimeoutError("timed out")), ErrorCode.TIMEOUT),
        (TimeoutError("timed out"), ErrorCode.TIMEOUT),
    ],
)
def test_cover_forge_maps_connection_and_timeout_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, expected: ErrorCode
) -> None:
    monkeypatch.setattr(cover_forge_client, "build_opener", lambda _handler: FakeOpener(error=error))

    result = run_cover_forge_adapter(
        params=CoverParams(title="连接测试"),
        output_path=tmp_path / "cover.png",
        settings=_settings(),
    )

    assert result.ok is False
    assert result.code == expected
    assert not (tmp_path / "cover.png").exists()


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (FakeResponse(b"", "image/png"), ErrorCode.NO_OUTPUT),
        (FakeResponse(PNG_BYTES, "image/jpeg"), ErrorCode.VALIDATION_FAILED),
        (FakeResponse(b"not-png", "image/png"), ErrorCode.VALIDATION_FAILED),
    ],
)
def test_cover_forge_rejects_empty_or_non_png_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: FakeResponse, expected: ErrorCode
) -> None:
    monkeypatch.setattr(cover_forge_client, "build_opener", lambda _handler: FakeOpener(response))

    result = run_cover_forge_adapter(
        params=CoverParams(title="输出测试"),
        output_path=tmp_path / "cover.png",
        settings=_settings(),
    )

    assert result.ok is False
    assert result.code == expected
    assert not (tmp_path / "cover.png").exists()
