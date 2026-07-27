from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    # Core
    data_dir: Path = Field(
        default=Path("output"),
        validation_alias=AliasChoices("DATA_DIR", "PIPELINE_DATA_DIR"),
    )
    profiles_dir: Path = Field(
        default=Path("profiles"),
        validation_alias=AliasChoices("PROFILES_DIR", "PIPELINE_PROFILES_DIR"),
    )

    # Gemini
    gemini_skill_dir: Path = Path(r"G:\Job\gemini-skill")
    gemini_image_command: str = ""

    # Photo-Process
    photo_process_dir: Path = Path(r"G:\Job\Photo-Process")
    photo_process_python: Path = Path(r"G:\Job\Photo-Process\.venv311\Scripts\python.exe")
    # Optional localhost Photo-Process Browser Worker endpoint.
    # Empty keeps the legacy one-shot CLI adapter for backwards compatibility.
    photo_process_worker_url: str = ""

    # MoneyPrinterTurbo
    mpt_dir: Path = Path(r"G:\Job\MoneyPrinterTurbo")
    mpt_python: Path = Path(r"G:\Job\MoneyPrinterTurbo\.venv\Scripts\python.exe")
    ai_art_bgm_dir: Path = Path(r"G:\Job\MoneyPrinterTurbo\resource\songs")

    # social-auto-upload
    sau_dir: Path = Path(r"G:\Job\social-auto-upload")
    sau_exe: Path = Path(r"G:\Job\social-auto-upload\.venv\Scripts\sau.exe")
    sau_bilibili_private_args: str = ""

    # Finance / AI Briefing
    finance_md_dir: Path = Path(r"G:\Job\Automation-Output\sajin\fund-daily")
    ai_briefing_dir: Path = Path(r"G:\Hermes-Output\每日AI简报")

    # Router LLM (optional — keyword fallback when absent)
    router_llm_base_url: str = ""
    router_llm_api_key: str = ""
    router_llm_model: str = ""

    # Environment tag
    env: str = "development"

    def validate_tool_paths(self) -> list[str]:
        """Return a list of diagnostic warnings. Empty list = all clear."""
        warnings: list[str] = []

        # Check paths that should exist
        path_checks: list[tuple[str, Path]] = [
            ("data_dir", self.data_dir),
            ("profiles_dir", self.profiles_dir),
            ("gemini_skill_dir", self.gemini_skill_dir),
            ("photo_process_dir", self.photo_process_dir),
            ("mpt_dir", self.mpt_dir),
            ("sau_dir", self.sau_dir),
            ("ai_art_bgm_dir", self.ai_art_bgm_dir),
            ("finance_md_dir", self.finance_md_dir),
            ("ai_briefing_dir", self.ai_briefing_dir),
        ]
        for name, path in path_checks:
            if not path.exists():
                warnings.append(f"[{name}] path does not exist: {path}")

        # Check executables
        exe_checks: list[tuple[str, Path]] = [
            ("photo_process_python", self.photo_process_python),
            ("mpt_python", self.mpt_python),
            ("sau_exe", self.sau_exe),
        ]
        for name, exe_path in exe_checks:
            if not exe_path.exists():
                warnings.append(f"[{name}] executable does not exist: {exe_path}")

        # Publish safety checks
        if not self.sau_bilibili_private_args:
            warnings.append("[sau_bilibili_private_args] not configured — Bilibili uploads will be blocked")

        return warnings

    def get_tool_status(self) -> dict[str, dict[str, object]]:
        """Return a structured status map for all external tools. Used by doctor."""
        tools: dict[str, dict[str, object]] = {}

        # Gemini
        gemini_ok = self.gemini_skill_dir.exists()
        tools["gemini"] = {
            "ok": gemini_ok,
            "dir": str(self.gemini_skill_dir),
            "mode": "mcp" if gemini_ok else ("cli" if self.gemini_image_command else "unavailable"),
        }

        # Photo-Process
        pp_ok = self.photo_process_dir.exists() and self.photo_process_python.exists()
        tools["photo_process"] = {
            "ok": pp_ok,
            "dir": str(self.photo_process_dir),
            "python": str(self.photo_process_python),
            "worker_url": self.photo_process_worker_url or None,
        }

        # MoneyPrinterTurbo
        mpt_ok = self.mpt_dir.exists() and self.mpt_python.exists()
        tools["mpt"] = {
            "ok": mpt_ok,
            "dir": str(self.mpt_dir),
            "python": str(self.mpt_python),
        }

        # social-auto-upload
        sau_ok = self.sau_dir.exists() and self.sau_exe.exists()
        tools["sau"] = {
            "ok": sau_ok,
            "dir": str(self.sau_dir),
            "exe": str(self.sau_exe),
            "bilibili_private_configured": bool(self.sau_bilibili_private_args),
        }

        return tools


def load_settings() -> Settings:
    return Settings()
