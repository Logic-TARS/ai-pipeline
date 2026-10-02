from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path, PurePosixPath

REQUIRED_MEMBERS = {
    "README.md",
    "MANIFEST.in",
    "pyproject.toml",
    "config/pipeline.defaults.yaml",
    "docs/configuration.md",
    "docs/publishing-runbook.md",
    "docs/smoke-testing.md",
    "docs/web-access-boundary.md",
    "examples/tasks/README.md",
    "examples/tasks/dry-run/task.example.json",
    "examples/tasks/local/task.ai-art.example.json",
    "examples/tasks/local/task.japanese.example.json",
    "examples/tasks/publish/task.publish.json",
    "profiles/anime.yaml",
    "profiles/finance.yaml",
    "src/content_pipeline/api/app.py",
    "src/content_pipeline/cli/main.py",
    "src/content_pipeline/web/static/app.js",
    "src/content_pipeline/web/static/content-studio.js",
    "src/content_pipeline/web/static/index.html",
    "src/content_pipeline/web/static/styles.css",
}

FORBIDDEN_PREFIXES = (
    ".github/",
    ".git/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "build/",
    "data/",
    "dist/",
    "output/",
)
FORBIDDEN_NAMES = {".env", ".env.example"}
FORBIDDEN_SUFFIXES = (".key", ".pem", ".crt", ".log", ".pyc", ".pyo")


def _normalize_member(name: str) -> str:
    parts = PurePosixPath(name).parts
    if len(parts) <= 1:
        return name
    return "/".join(parts[1:])


def _is_forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    if name in FORBIDDEN_NAMES or path.name in FORBIDDEN_NAMES:
        return True
    if name.startswith(".env.") or path.name.startswith(".env."):
        return True
    if path.name.startswith("diagnostics") and path.name.endswith(".zip"):
        return True
    if "__pycache__" in path.parts:
        return True
    if name.endswith(FORBIDDEN_SUFFIXES):
        return True
    return any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate ai-pipeline source distribution contents")
    parser.add_argument("sdist", type=Path)
    args = parser.parse_args(argv)

    if not args.sdist.is_file():
        print(f"sdist not found: {args.sdist}", file=sys.stderr)
        return 1

    errors: list[str] = []
    try:
        with tarfile.open(args.sdist, "r:gz") as archive:
            names = {_normalize_member(member.name) for member in archive.getmembers() if member.name}
    except tarfile.TarError as exc:
        print(f"invalid sdist archive: {exc}", file=sys.stderr)
        return 1

    missing = sorted(REQUIRED_MEMBERS - names)
    forbidden = sorted(name for name in names if _is_forbidden(name))

    if missing:
        errors.append("missing required sdist members: " + ", ".join(missing))
    if forbidden:
        errors.append("forbidden sdist members: " + ", ".join(forbidden[:10]))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"sdist content ok: {args.sdist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
