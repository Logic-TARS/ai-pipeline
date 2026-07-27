import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_pipeline.tools import gemini_mcp_client


def test_generate_many_starts_fresh_then_reuses_session(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def generate_image(self, _prompt: str, **kwargs) -> Path:
            calls.append(kwargs)
            path = tmp_path / f"source-{len(calls)}.png"
            path.write_bytes(b"image")
            return path

    monkeypatch.setattr(gemini_mcp_client, "GeminiMcpClient", FakeClient)
    results = gemini_mcp_client.generate_many(
        skill_dir=tmp_path,
        output_dir=tmp_path / "output",
        prompt="prompt",
        count=2,
        timeout=10,
        full_size=False,
    )

    assert [call["new_session"] for call in calls] == [True, False]
    assert [call["full_size"] for call in calls] == [False, False]
    assert [path.name for path in results] == ["01.png", "02.png"]


def test_request_timeout_is_not_blocked_by_silent_stdout(tmp_path: Path) -> None:
    client = gemini_mcp_client.GeminiMcpClient(tmp_path, tmp_path)
    client.proc = SimpleNamespace(
        stdin=io.StringIO(),
        poll=lambda: None,
    )
    client._stderr.append("diagnostic line")

    with pytest.raises(TimeoutError, match="diagnostic line"):
        client._request("tools/call", {}, timeout=0.01)


def test_stderr_reader_keeps_a_bounded_diagnostic_tail(tmp_path: Path) -> None:
    client = gemini_mcp_client.GeminiMcpClient(tmp_path, tmp_path)
    client.proc = SimpleNamespace(stderr=io.StringIO("".join(f"line-{index}\n" for index in range(150))))

    client._read_stderr()

    assert len(client._stderr) == 100
    assert client._stderr[0] == "line-50"
    assert client._stderr[-1] == "line-149"
