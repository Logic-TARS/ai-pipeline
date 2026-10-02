from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path, PurePosixPath

REQUIRED_MEMBERS = {
    "content_pipeline/config/__init__.py",
    "content_pipeline/config/pipeline.defaults.yaml",
    "content_pipeline/api/app.py",
    "content_pipeline/cli/main.py",
    "content_pipeline/web/static/app.js",
    "content_pipeline/web/static/content-studio.js",
    "content_pipeline/web/static/index.html",
    "content_pipeline/web/static/styles.css",
}

FORBIDDEN_PREFIXES = (
    "tests/",
    "output/",
    "data/",
    ".github/",
    ".git/",
)
FORBIDDEN_NAMES = {".env", ".env.example"}
FORBIDDEN_SUFFIXES = (".key", ".pem", ".crt", ".log", ".pyc", ".pyo")
REQUIRED_METADATA_FIELDS = (
    "Name: ai-pipeline",
    "Requires-Python: >=3.11",
    "Description-Content-Type: text/markdown",
    "Classifier: Framework :: FastAPI",
    "Classifier: Programming Language :: Python :: 3.11",
    "Classifier: Topic :: Multimedia :: Video",
    "Keywords: automation,content-pipeline,social-media,video",
)


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
    parser = argparse.ArgumentParser(description="Validate ai-pipeline wheel contents")
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)

    if not args.wheel.is_file():
        print(f"wheel not found: {args.wheel}", file=sys.stderr)
        return 1

    errors: list[str] = []
    try:
        with zipfile.ZipFile(args.wheel) as archive:
            names = set(archive.namelist())
            dist_info_dirs = sorted(
                {name.split("/", 1)[0] for name in names if name.startswith("ai_pipeline-") and ".dist-info/" in name}
            )
            if len(dist_info_dirs) != 1:
                errors.append("expected exactly one ai_pipeline dist-info directory")
                dist_info = "ai_pipeline-unknown.dist-info"
            else:
                dist_info = dist_info_dirs[0]
            required_members = REQUIRED_MEMBERS | {f"{dist_info}/entry_points.txt", f"{dist_info}/METADATA"}
            missing = sorted(required_members - names)
            forbidden = sorted(name for name in names if _is_forbidden(name))
            entry_points = (
                archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")
                if f"{dist_info}/entry_points.txt" in names
                else ""
            )
            metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8") if f"{dist_info}/METADATA" in names else ""
    except zipfile.BadZipFile as exc:
        print(f"invalid wheel archive: {exc}", file=sys.stderr)
        return 1

    if missing:
        errors.append("missing required wheel members: " + ", ".join(missing))
    if forbidden:
        errors.append("forbidden wheel members: " + ", ".join(forbidden[:10]))
    if "ai-pipeline = content_pipeline.cli.main:main" not in entry_points:
        errors.append("missing ai-pipeline console entry point")
    missing_metadata = [field for field in REQUIRED_METADATA_FIELDS if field not in metadata]
    if missing_metadata:
        errors.append("missing required wheel metadata fields: " + ", ".join(missing_metadata))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"wheel content ok: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
