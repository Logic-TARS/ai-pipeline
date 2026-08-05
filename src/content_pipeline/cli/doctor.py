"""ai-popline doctor — environment and tool diagnostics."""

from __future__ import annotations

import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from content_pipeline.api.network import validate_bind_configuration
from content_pipeline.settings import load_settings


def _check(label: str, ok: bool, detail: str = "") -> str:
    mark = "[OK]" if ok else "[FAIL]"
    line = f"  {mark} {label}"
    if detail:
        line += f"  ({detail})"
    return line


def run_doctor() -> int:
    """Run environment diagnostics and return exit code (0 = all clear)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError):
        pass

    all_ok = True

    print("AI Popline Doctor")
    print("=" * 50)

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)
    if not py_ok:
        all_ok = False
    print("\n[Python]")
    print(_check(f"Version {py_ver}", py_ok, "needs >=3.11" if not py_ok else ""))

    # 2. Config
    print("\n[Config]")
    try:
        settings = load_settings()
        print(_check(".env loaded", True, f"env={settings.env}"))
    except Exception as exc:
        print(_check(".env loaded", False, str(exc)))
        all_ok = False
        return 1

    # 3. External tools
    print("\n[External Tools]")
    tool_status = settings.get_tool_status()
    for tool_name, status in tool_status.items():
        ok = bool(status["ok"])
        if not ok:
            all_ok = False
        label = f"{tool_name}: {'available' if ok else 'unavailable'}"
        print(_check(label, ok))

        if tool_name == "gemini" and status["dir"]:
            print(f"      dir: {status['dir']}")
            print(f"      mode: {status['mode']}")
        elif tool_name == "photo_process":
            if status["dir"]:
                print(f"      dir: {status['dir']}")
            if status["python"]:
                print(f"      python: {status['python']}")
            if status.get("worker_url"):
                print(f"      worker: {status['worker_url']}")
        elif tool_name == "sau":
            if status["dir"]:
                print(f"      dir: {status['dir']}")
            print(f"      bilibili_private: {status.get('bilibili_private_configured', False)}")

    # 4. Config warnings
    print("\n[Config Validation]")
    warnings = settings.validate_tool_paths()
    if warnings:
        for w in warnings:
            print(f"  ! {w}")
    else:
        print(_check("All configured paths valid", True))

    # 5. Web listener safety
    print("\n[Web Security]")
    web_errors = validate_bind_configuration(
        settings,
        host=settings.web_bind_host,
        ssl_certfile=settings.web_tls_certfile,
        ssl_keyfile=settings.web_tls_keyfile,
    )
    web_ok = not web_errors
    if not web_ok:
        all_ok = False
    print(_check(f"Bind policy: {settings.web_bind_host}:{settings.web_port}", web_ok))
    for error in web_errors:
        print(f"  ! {error}")

    # 6. Output directory
    print("\n[Output]")
    data_ok = settings.data_dir.exists() or _ensure_dir(settings.data_dir)
    if not data_ok:
        all_ok = False
    print(_check(f"Data dir writable: {settings.data_dir}", data_ok))

    # 7. Profiles
    print("\n[Profiles]")
    profiles_ok = settings.profiles_dir.exists()
    if not profiles_ok:
        all_ok = False
    print(_check(f"Profiles dir: {settings.profiles_dir}", profiles_ok))
    if profiles_ok:
        yaml_files = sorted(settings.profiles_dir.glob("*.yaml"))
        for yf in yaml_files:
            print(f"      {yf.name}")

    print()
    if all_ok:
        print("[OK] All checks passed.")
        return 0
    else:
        print("[FAIL] Some checks failed. Review the items above.")
        return 1


def run_doctor_bundle(output_path: Path) -> int:
    """Run doctor and bundle diagnostics to a zip file."""
    settings = load_settings()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write diagnostic summary
        summary_lines = [
            "ai-popline doctor bundle",
            f"Generated: {datetime.now(UTC).isoformat()}",
            f"Python: {sys.version}",
            f"Platform: {sys.platform}",
            "",
            "--- Settings ---",
        ]
        for field_name, field_value in sorted(settings.model_dump().items()):
            summary_lines.append(f"{field_name}: {field_value}")
        summary_lines.append("")
        summary_lines.append("--- Warnings ---")
        summary_lines.extend(settings.validate_tool_paths())
        zf.writestr("diagnostics.txt", "\n".join(summary_lines))

    print(f"Diagnostics bundle written to: {output_path}")
    return 0


def _ensure_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        (path / ".write_test").write_text("test")
        (path / ".write_test").unlink()
        return True
    except OSError:
        return False
