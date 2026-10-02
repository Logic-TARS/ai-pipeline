from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ConfigError

__all__ = ["ImageGenProfile", "Profile", "UploadProfile", "VideoGenProfile", "load_profile"]


class ImageGenProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=4, ge=1, le=20)
    prompt_template: str = Field(min_length=1)
    full_size: bool = True


class VideoGenProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect: str = Field(default="9:16", min_length=1, max_length=20)
    voice_name: str = Field(default="", max_length=120)
    subtitle_enabled: bool = True
    subject_template: str = Field(default="{topic}", min_length=1)
    script_template: str = Field(default="{script}", min_length=1)


class UploadProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(default="bilibili", min_length=1, max_length=40)
    account: str = Field(min_length=1, max_length=120)
    tid: int = Field(ge=1)
    title_template: str = Field(default="{topic}", min_length=1, max_length=120)
    desc_template: str = Field(default="{script}", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    visibility: str = Field(default="private", min_length=1, max_length=40)
    schedule: str | None = Field(default=None, max_length=120)


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    image_gen: ImageGenProfile
    video_gen: VideoGenProfile
    upload: UploadProfile


def load_profile(content_type: str, profiles_dir: Path) -> Profile:
    path = profiles_dir / f"{content_type}.yaml"
    if not path.is_file():
        raise ConfigError(f"profile not found: {path}")
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"could not read profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid profile {path}: {exc}") from exc
    try:
        profile = Profile.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid profile {path}: {exc}") from exc
    if profile.upload.visibility != "private":
        raise ConfigError("profiles must default to upload.visibility=private")
    return profile
