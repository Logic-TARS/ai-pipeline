from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from content_pipeline.models import AdapterResult, CoverParams, ErrorCode
from content_pipeline.settings import Settings

__all__ = ["run_cover_forge_adapter"]

_TOOL_NAME = "Cover-Forge"
_MAX_BACKGROUND_BYTES = 5 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_BACKGROUND_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def run_cover_forge_adapter(
    *,
    params: CoverParams,
    output_path: Path,
    settings: Settings,
) -> AdapterResult:
    try:
        payload = _request_payload(params)
    except (OSError, ValueError) as exc:
        return _failure(ErrorCode.INPUT_ERROR, str(exc))

    request = Request(
        settings.cover_forge_url.rstrip("/") + "/api/covers",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "image/png", "Content-Type": "application/json"},
        method="POST",
    )
    evidence: dict[str, object] = {"timeout_seconds": settings.cover_forge_timeout_seconds}

    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=settings.cover_forge_timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            body = response.read()
            evidence["http_status"] = response.status
            evidence["content_type"] = content_type
    except HTTPError as exc:
        return _http_failure(exc, evidence)
    except TimeoutError as exc:
        return _failure(
            ErrorCode.TIMEOUT,
            f"Cover-Forge timed out after {settings.cover_forge_timeout_seconds} seconds: {_safe_text(str(exc))}",
            evidence=evidence,
        )
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return _failure(
                ErrorCode.TIMEOUT,
                f"Cover-Forge timed out after {settings.cover_forge_timeout_seconds} seconds",
                evidence=evidence,
            )
        return _failure(
            ErrorCode.EXTERNAL_TOOL_FAILED,
            f"Cover-Forge is unavailable: {_safe_text(str(exc.reason))}",
            evidence=evidence,
        )
    except OSError as exc:
        return _failure(
            ErrorCode.EXTERNAL_TOOL_FAILED,
            f"Cover-Forge request failed: {_safe_text(str(exc))}",
            evidence=evidence,
        )

    if not body:
        return _failure(ErrorCode.NO_OUTPUT, "Cover-Forge returned an empty response", evidence=evidence)
    if content_type != "image/png":
        return _failure(
            ErrorCode.VALIDATION_FAILED,
            f"Cover-Forge returned unsupported content type: {_safe_text(content_type)}",
            evidence=evidence,
        )
    if not body.startswith(_PNG_SIGNATURE):
        return _failure(
            ErrorCode.VALIDATION_FAILED,
            "Cover-Forge returned data without a valid PNG signature",
            evidence=evidence,
        )

    try:
        _atomic_write(output_path, body)
    except OSError as exc:
        return _failure(
            ErrorCode.NO_OUTPUT,
            f"Cover-Forge output could not be saved: {_safe_text(str(exc))}",
            evidence=evidence,
        )
    return AdapterResult(
        ok=True,
        tool=_TOOL_NAME,
        code=ErrorCode.OK,
        artifacts={"cover_path": str(output_path)},
        evidence=evidence,
    )


def _request_payload(params: CoverParams) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": params.title,
        "size": params.size,
        "template": params.template,
        "titlePosition": params.title_position,
        "backgroundTransform": {
            "scale": params.background_scale,
            "positionX": params.background_position_x,
            "positionY": params.background_position_y,
        },
    }
    if params.background_image is not None:
        payload["backgroundImage"] = _background_data_url(params.background_image)
    return payload


def _background_data_url(path: Path) -> str:
    source = path.expanduser()
    if not source.is_file():
        raise ValueError(f"background image does not exist: {source}")
    mime_type = _BACKGROUND_TYPES.get(source.suffix.lower())
    if mime_type is None:
        raise ValueError("background image must be PNG, JPEG, or WebP")

    with source.open("rb") as handle:
        data = handle.read(_MAX_BACKGROUND_BYTES + 1)
    if len(data) > _MAX_BACKGROUND_BYTES:
        raise ValueError("background image exceeds the 5 MiB limit")
    if not _matches_image_type(data, mime_type):
        raise ValueError(f"background image content does not match {mime_type}")
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _matches_image_type(data: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return data.startswith(_PNG_SIGNATURE)
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def _http_failure(exc: HTTPError, evidence: dict[str, object]) -> AdapterResult:
    evidence = {**evidence, "http_status": exc.code}
    try:
        body = exc.read(64 * 1024)
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    cover_forge_error: dict[str, object] = {"http_status": exc.code}
    message = f"Cover-Forge HTTP {exc.code}"
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        error = payload["error"]
        code = _safe_text(str(error.get("code", "")))[:120]
        detail = _safe_text(str(error.get("message", "")))[:1000]
        if code:
            cover_forge_error["code"] = code
        if detail:
            cover_forge_error["message"] = detail
            message = detail

    error_code = ErrorCode.INPUT_ERROR if 400 <= exc.code < 500 else ErrorCode.EXTERNAL_TOOL_FAILED
    return _failure(
        error_code,
        message,
        evidence=evidence,
        raw={"cover_forge_error": cover_forge_error},
    )


def _atomic_write(output_path: Path, data: bytes) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_text(value: str) -> str:
    value = re.sub(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", "[redacted data URL]", value)
    value = re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", value)
    return " ".join(value.replace("\x00", "").split())


def _failure(
    code: ErrorCode,
    message: str,
    *,
    evidence: dict[str, object] | None = None,
    raw: dict[str, object] | None = None,
) -> AdapterResult:
    return AdapterResult(
        ok=False,
        tool=_TOOL_NAME,
        code=code,
        message=_safe_text(message)[:2000],
        evidence=evidence or {},
        raw=raw or {},
    )
