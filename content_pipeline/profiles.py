from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .errors import ConfigError


class ImageGenProfile(BaseModel):
    count: int = 4
    prompt_template: str
    full_size: bool = True


class VideoGenProfile(BaseModel):
    aspect: str = "9:16"
    voice_name: str = ""
    subtitle_enabled: bool = True
    subject_template: str = "{topic}"
    script_template: str = "{script}"


class UploadProfile(BaseModel):
    platform: str = "bilibili"
    account: str
    tid: int
    title_template: str = "{topic}"
    desc_template: str = "{script}"
    tags: list[str] = Field(default_factory=list)
    visibility: str = "private"
    schedule: str | None = None


class Profile(BaseModel):
    name: str
    image_gen: ImageGenProfile
    video_gen: VideoGenProfile
    upload: UploadProfile


def load_profile(content_type: str, profiles_dir: Path) -> Profile:
    path = profiles_dir / f"{content_type}.yaml"
    if not path.is_file():
        raise ConfigError(f"profile not found: {path}")
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile = Profile.model_validate(data)
    if profile.upload.visibility != "private":
        raise ConfigError("profiles must default to upload.visibility=private")
    return profile
