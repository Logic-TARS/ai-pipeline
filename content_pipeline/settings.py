from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    data_dir: Path = _env_path("PIPELINE_DATA_DIR", "output")
    profiles_dir: Path = _env_path("PIPELINE_PROFILES_DIR", "profiles")
    gemini_skill_dir: Path = _env_path("GEMINI_SKILL_DIR", r"G:\Job\gemini-skill")
    gemini_image_command: str = os.getenv("GEMINI_IMAGE_COMMAND", "")
    photo_process_dir: Path = _env_path("PHOTO_PROCESS_DIR", r"G:\Job\Photo-Process")
    photo_process_python: Path = _env_path(
        "PHOTO_PROCESS_PYTHON",
        r"G:\Job\Photo-Process\.venv311\Scripts\python.exe",
    )
    # Optional localhost Photo-Process Browser Worker endpoint. Empty keeps the
    # legacy one-shot CLI adapter for backwards compatibility.
    photo_process_worker_url: str = os.getenv("PHOTO_PROCESS_WORKER_URL", "")
    mpt_dir: Path = _env_path("MPT_DIR", r"G:\Job\MoneyPrinterTurbo")
    mpt_python: Path = _env_path(
        "MPT_PYTHON",
        r"G:\Job\MoneyPrinterTurbo\.venv\Scripts\python.exe",
    )
    ai_art_bgm_dir: Path = _env_path(
        "AI_ART_BGM_DIR",
        r"G:\Job\MoneyPrinterTurbo\resource\songs",
    )
    sau_dir: Path = _env_path("SAU_DIR", r"G:\Job\social-auto-upload")
    sau_exe: Path = _env_path(
        "SAU_EXE",
        r"G:\Job\social-auto-upload\.venv\Scripts\sau.exe",
    )
    sau_bilibili_private_args: str = os.getenv("SAU_BILIBILI_PRIVATE_ARGS", "")
    finance_md_dir: Path = _env_path(
        "FINANCE_MD_DIR",
        r"G:\Job\Automation-Output\sajin\fund-daily",
    )
    ai_briefing_dir: Path = _env_path(
        "AI_BRIEFING_DIR",
        r"G:\Hermes-Output\每日AI简报",
    )
    router_llm_base_url: str = os.getenv("ROUTER_LLM_BASE_URL", "")
    router_llm_api_key: str = os.getenv("ROUTER_LLM_API_KEY", "")
    router_llm_model: str = os.getenv("ROUTER_LLM_MODEL", "")


def load_settings() -> Settings:
    return Settings()
