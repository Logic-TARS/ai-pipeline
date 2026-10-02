"""Packaged Web operator console assets."""

from pathlib import Path

WEB_STATIC_DIR = Path(__file__).resolve().parent / "static"

__all__ = ["WEB_STATIC_DIR"]
