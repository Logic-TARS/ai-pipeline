from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from content_pipeline.errors import ConfigError, ExternalToolError
from content_pipeline.media_validation import validate_images
from content_pipeline.models import AdapterResult, ErrorCode
from content_pipeline.settings import Settings
from content_pipeline.tools.common import run_command

SOURCE_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def photo_process_contract(settings: Settings) -> dict[str, object]:
    return {
        "name": "Photo-Process",
        "boundary": (
            "local Browser Worker HTTP adapter when PHOTO_PROCESS_WORKER_URL is set; "
            "otherwise CLI JSON adapter"
        ),
        "cwd": str(settings.photo_process_dir),
        "python": str(settings.photo_process_python),
        "command": [
            str(settings.photo_process_python),
            str(settings.photo_process_dir / "main.py"),
            "comic",
            "--image",
            "<image>",
            "--prompt",
            "<prompt>",
            "--json",
        ],
        "timeout_seconds": 900,
        "result_schema": {
            "ok": "boolean success flag",
            "tool": "Photo-Process",
            "code": " | ".join(
                [
                    "OK",
                    "CONFIG_ERROR",
                    "INPUT_ERROR",
                    "SOURCE_NOT_FOUND",
                    "EXTERNAL_TOOL_FAILED",
                    "NO_OUTPUT",
                    "VALIDATION_FAILED",
                    "DESKTOP_HELPER_UNAVAILABLE",
                    "AUTH_REQUIRED",
                    "BROWSER_BUSY",
                    "GEM_ACCESS_FAILED",
                    "UI_CHANGED",
                    "TIMEOUT",
                ]
            ),
            "message": "human-readable detail or null",
            "artifacts": {
                "image_path": "absolute generated image path from Photo-Process",
                "processed_path": "absolute copied parent-job artifact path",
                "width": "integer pixel width",
                "height": "integer pixel height",
                "format": "validated image format",
                "target_aspect_ratio": "parsed ratio from prompt when present",
                "source_done_path": "optional moved original path",
            },
            "evidence": {
                "command": "adapter command argv",
                "cwd": "adapter working directory",
                "timeout_seconds": 900,
                "validation": "validated copied image metadata",
                "reused_existing": "true when an existing parent artifact was reused",
            },
            "raw": {
                "photo_process_json": "final JSON object from Photo-Process stdout when available",
                "stderr_tail": "stderr tail when command execution failed",
            },
        },
        "owned_behavior": [
            "Gemini browser automation",
            "current-response candidate selection",
            "image decode and aspect-ratio validation",
        ],
        "caller_rules": [
            "Pass staged copies when originals must be preserved.",
            "Parse only the final JSON object from stdout.",
            "Validate the returned artifact before committing it to the parent job.",
        ],
        "foreground_debug": {
            "purpose": "Human inspection only; not completion evidence.",
            "modes": ["automation", "desktop"],
            "entrypoint": str(settings.photo_process_dir / "启动调试浏览器.py"),
            "command": [
                str(settings.photo_process_python),
                str(settings.photo_process_dir / "启动调试浏览器.py"),
                "<url>",
            ],
            "mcp_tool": "open_photo_process_debug",
            "cli": "python -m content_pipeline.diagnostics photo-debug --mode automation --url <url>",
            "desktop_helper": "python -m content_pipeline.desktop_browser_helper",
            "desktop_cli": "python -m content_pipeline.diagnostics photo-debug --mode desktop --url <url>",
            "install_desktop_helper_task": "scripts/install_desktop_browser_helper_task.ps1",
            "uninstall_desktop_helper_task": "scripts/uninstall_desktop_browser_helper_task.ps1",
            "rules": [
                "Use this instead of launching Chrome directly when a human needs to watch Gemini.",
                "Do not treat a visible browser as job success.",
                "The normal generation adapter remains main.py comic --json.",
                "Use desktop mode only after starting the localhost desktop browser helper "
                "in the user desktop session.",
                "Agents may install the desktop helper scheduled task, but must not launch Chrome "
                "directly as a substitute.",
            ],
        },
    }


def scan_source_images(source_dir: Path, source_files: list[str] | None = None) -> list[Path]:
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ConfigError(f"AI art source directory does not exist: {source_dir}")
    if source_files:
        selected: list[Path] = []
        for filename in source_files:
            if Path(filename).name != filename:
                raise ConfigError(f"source_files entries must be plain filenames: {filename}")
            path = (source_dir / filename).resolve()
            if path.parent != source_dir or not path.is_file() or path.suffix.lower() not in SOURCE_IMAGE_SUFFIXES:
                raise ConfigError(f"selected source image is invalid or missing: {path}")
            selected.append(path)
        if len(set(selected)) != len(selected):
            raise ConfigError("source_files must not contain duplicates")
        return selected
    return sorted(
        (path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in SOURCE_IMAGE_SUFFIXES),
        key=_natural_key,
    )


def call_photo_process(
    *,
    source: Path,
    prompt: str,
    output_path: Path,
    settings: Settings,
    target_gem_name: str | None = None,
    target_gem_url: str | None = None,
) -> Path:
    result = run_photo_process_adapter(
        source=source,
        prompt=prompt,
        output_path=output_path,
        settings=settings,
        target_gem_name=target_gem_name,
        target_gem_url=target_gem_url,
    )
    if not result.ok:
        raise ExternalToolError(f"Photo-Process failed [{result.code.value}]: {result.message or 'unknown error'}")
    processed_path = result.artifacts.get("processed_path")
    if not processed_path:
        raise ExternalToolError("Photo-Process adapter succeeded without processed_path")
    return Path(str(processed_path))


def run_photo_process_adapter(
    *,
    source: Path,
    prompt: str,
    output_path: Path,
    settings: Settings,
    target_gem_name: str | None = None,
    target_gem_url: str | None = None,
) -> AdapterResult:
    for existing in sorted(output_path.parent.glob(f"{output_path.stem}.*")) if output_path.parent.exists() else []:
        if existing.suffix.lower() in SOURCE_IMAGE_SUFFIXES and existing.is_file():
            try:
                validation = validate_images([existing], 1)
            except Exception as exc:
                return _failure(ErrorCode.VALIDATION_FAILED, str(exc), artifacts={"processed_path": str(existing)})
            return _success(
                image_path=existing,
                processed_path=existing,
                validation=validation,
                evidence={"reused_existing": True},
                raw={},
            )
    if not source.is_file():
        return _failure(ErrorCode.SOURCE_NOT_FOUND, f"source image does not exist: {source}")
    if settings.photo_process_worker_url.strip():
        return _run_photo_process_worker_adapter(
            source=source,
            prompt=prompt,
            output_path=output_path,
            settings=settings,
            target_gem_name=target_gem_name,
            target_gem_url=target_gem_url,
        )
    if not settings.photo_process_python.is_file():
        return _failure(ErrorCode.CONFIG_ERROR, f"Photo-Process Python not found: {settings.photo_process_python}")
    main_py = settings.photo_process_dir / "main.py"
    if not main_py.is_file():
        return _failure(ErrorCode.CONFIG_ERROR, f"Photo-Process entrypoint not found: {main_py}")

    command = [
        str(settings.photo_process_python),
        str(main_py),
        "comic",
        "--image",
        str(source.resolve()),
        "--prompt",
        prompt,
    ]
    if target_gem_name:
        command.extend(["--target-gem-name", target_gem_name])
    if target_gem_url:
        command.extend(["--target-gem-url", target_gem_url])
    command.append("--json")
    evidence = {
        "command": command,
        "cwd": str(settings.photo_process_dir),
        "timeout_seconds": 900,
        "reused_existing": False,
    }

    try:
        result = run_command(
            command,
            cwd=settings.photo_process_dir,
            timeout=900,
            retries=0,
            env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        return _failure(ErrorCode.TIMEOUT, f"Photo-Process timed out after 900 seconds: {exc}", evidence=evidence)
    except ExternalToolError as exc:
        message = str(exc)
        raw: dict[str, object] = {"stderr_tail": message[-1000:]}
        try:
            payload = _parse_json_result(message)
        except ExternalToolError:
            payload = {}
        if payload:
            raw["photo_process_json"] = payload
        if _looks_like_gem_access_failure(message):
            return _failure(ErrorCode.GEM_ACCESS_FAILED, message, evidence=evidence, raw=raw)
        if payload and not payload.get("success"):
            return _failure(_error_code_from_payload(payload), message, evidence=evidence, raw=raw)
        return _failure(ErrorCode.EXTERNAL_TOOL_FAILED, message, evidence=evidence, raw=raw)

    try:
        payload = _parse_json_result(result.stdout)
    except ExternalToolError as exc:
        return _failure(
            ErrorCode.NO_OUTPUT,
            str(exc),
            evidence=evidence,
            raw={"stdout_tail": result.stdout[-1000:], "stderr_tail": result.stderr[-1000:]},
        )
    if not payload.get("success"):
        return _failure(
            _error_code_from_payload(payload),
            str(payload.get("error", "unknown error")),
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    generated = Path(str(payload.get("image_path", ""))).expanduser()
    if not generated.is_absolute():
        generated = settings.photo_process_dir / generated
    if not generated.is_file():
        return _failure(
            ErrorCode.NO_OUTPUT,
            f"Photo-Process reported missing image_path: {generated}",
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    try:
        validate_images([generated], 1)
    except Exception as exc:
        return _failure(
            ErrorCode.VALIDATION_FAILED,
            str(exc),
            artifacts={"image_path": str(generated)},
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target = output_path.with_suffix(generated.suffix.lower())
    shutil.copy2(generated, target)
    try:
        validation = validate_images([target], 1)
    except Exception as exc:
        return _failure(
            ErrorCode.VALIDATION_FAILED,
            str(exc),
            artifacts={"image_path": str(generated), "processed_path": str(target)},
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    return _success(
        image_path=generated,
        processed_path=target,
        validation=validation,
        evidence=evidence,
        raw={"photo_process_json": payload},
        payload=payload,
    )


def _run_photo_process_worker_adapter(
    *,
    source: Path,
    prompt: str,
    output_path: Path,
    settings: Settings,
    target_gem_name: str | None,
    target_gem_url: str | None,
) -> AdapterResult:
    worker_url = settings.photo_process_worker_url.rstrip("/")
    endpoint = f"{worker_url}/api/comic"
    evidence: dict[str, object] = {
        "worker_url": worker_url,
        "endpoint": endpoint,
        "timeout_seconds": 900,
        "reused_existing": False,
    }
    body = json.dumps(
        {
            "image_path": str(source.resolve()),
            "prompt": prompt,
            "target_gem_name": target_gem_name,
            "target_gem_url": target_gem_url,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        # Explicitly bypass system proxies: this contract is localhost-only.
        with build_opener(ProxyHandler({})).open(request, timeout=900) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        code = ErrorCode.BROWSER_BUSY if exc.code == 409 else ErrorCode.EXTERNAL_TOOL_FAILED
        return _failure(code, f"Photo-Process Browser Worker HTTP {exc.code}: {detail}", evidence=evidence)
    except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return _failure(
            ErrorCode.EXTERNAL_TOOL_FAILED,
            f"Photo-Process Browser Worker unavailable at {worker_url}: {exc}",
            evidence=evidence,
        )
    if not isinstance(payload, dict):
        return _failure(
            ErrorCode.NO_OUTPUT, "Photo-Process Browser Worker returned a non-object response", evidence=evidence
        )
    if not payload.get("success"):
        return _failure(
            _error_code_from_payload(payload),
            str(payload.get("error", "unknown worker error")),
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    generated = Path(str(payload.get("image_path", ""))).expanduser()
    if not generated.is_file():
        return _failure(
            ErrorCode.NO_OUTPUT,
            f"Photo-Process Browser Worker reported missing image_path: {generated}",
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    try:
        validate_images([generated], 1)
    except Exception as exc:
        return _failure(
            ErrorCode.VALIDATION_FAILED,
            str(exc),
            artifacts={"image_path": str(generated)},
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target = output_path.with_suffix(generated.suffix.lower())
    shutil.copy2(generated, target)
    try:
        validation = validate_images([target], 1)
    except Exception as exc:
        return _failure(
            ErrorCode.VALIDATION_FAILED,
            str(exc),
            artifacts={"image_path": str(generated), "processed_path": str(target)},
            evidence=evidence,
            raw={"photo_process_json": payload},
        )
    return _success(
        image_path=generated,
        processed_path=target,
        validation=validation,
        evidence=evidence,
        raw={"photo_process_json": payload},
        payload=payload,
    )


def archive_source(source: Path, archive_dir: Path) -> Path:
    if not source.exists():
        raise ConfigError(f"source image is no longer available for archiving: {source}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / source.name
    counter = 1
    while target.exists():
        target = archive_dir / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    return Path(shutil.move(str(source), str(target)))


def _parse_json_result(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ExternalToolError(f"Photo-Process did not return a JSON result: {stdout[-1000:]}")


def _success(
    *,
    image_path: Path,
    processed_path: Path,
    validation: object,
    evidence: dict[str, object],
    raw: dict[str, object],
    payload: dict | None = None,
) -> AdapterResult:
    first_file = validation.files[0]
    artifacts: dict[str, object] = {
        "image_path": str(image_path),
        "processed_path": str(processed_path),
        "format": first_file.format,
        "width": first_file.width,
        "height": first_file.height,
    }
    if payload:
        for key in ("target_aspect_ratio", "source_done_path"):
            if payload.get(key) is not None:
                artifacts[key] = payload[key]
    return AdapterResult(
        ok=True,
        tool="Photo-Process",
        code=ErrorCode.OK,
        artifacts=artifacts,
        evidence={**evidence, "validation": validation.model_dump(mode="json")},
        raw=raw,
    )


def _failure(
    code: ErrorCode,
    message: str,
    *,
    artifacts: dict[str, object] | None = None,
    evidence: dict[str, object] | None = None,
    raw: dict[str, object] | None = None,
) -> AdapterResult:
    return AdapterResult(
        ok=False,
        tool="Photo-Process",
        code=code,
        message=message,
        artifacts=artifacts or {},
        evidence=evidence or {},
        raw=raw or {},
    )


def _error_code_from_payload(payload: dict) -> ErrorCode:
    error_type = str(payload.get("error_type", "")).lower()
    if error_type in {"auth_required", "authentication_required"}:
        return ErrorCode.AUTH_REQUIRED
    if error_type in {"browser_busy", "profile_busy"}:
        return ErrorCode.BROWSER_BUSY
    if error_type in {"ui_changed", "selector_changed"}:
        return ErrorCode.UI_CHANGED
    if "gem" in error_type and "access" in error_type:
        return ErrorCode.GEM_ACCESS_FAILED
    if error_type in {"input_error", "invalid_input"}:
        return ErrorCode.INPUT_ERROR
    if error_type in {"no_output", "missing_output"}:
        return ErrorCode.NO_OUTPUT
    if "timeout" in error_type:
        return ErrorCode.TIMEOUT
    if "validation" in error_type:
        return ErrorCode.VALIDATION_FAILED
    return ErrorCode.EXTERNAL_TOOL_FAILED


def _looks_like_gem_access_failure(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "GEM_ACCESS_FAILED",
            "AUTH_REQUIRED",
            "Gemini 显示登录入口",
            "Gemini did not stay on the requested Gem URL",
            "直达 Gem URL 打开后被重定向",
            "无法进入目标 Gem",
        )
    )


def _natural_key(path: Path) -> list[object]:
    import re

    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]
