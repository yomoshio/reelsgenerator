import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything read from `.env` and REELSMITH_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="REELSMITH_", env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    jobs: Path = Path("jobs")
    styles: Path = Path("styles")
    library: Path = Path("library/things")
    outbox: Path = Path("outbox")
    runtime: Path = Path("runtime")

    llm_url: str = "http://localhost:11434/v1"
    speech_url: str = "http://localhost:8000"
    tts: Literal["chatterbox", "qwen"] = Field(
        default="chatterbox",
        description="Who reads the narrator: Chatterbox at voice_url, or Qwen3-TTS in speech.",
    )
    voice_url: str = "http://localhost:8001"
    stress: Path = Field(
        default=Path("stress.txt"),
        description="Words with the stress marked by hand; they overrule the marker.",
    )

    style: str = "blackout"
    language: str = "ru"
    planner: str = "qwen3.5:27b"
    editor: str = Field(default="", description="Empty skips the editing pass.")
    director: str = "qwen3.5:27b"
    coder: str = "qwen3-coder-next"
    vision: str = "qwen3.5:27b"
    temperature: float = Field(default=0.7, ge=0, le=2)
    coder_temperature: float = Field(default=0.3, ge=0, le=2)
    reasoning: str = "none"

    rewrites: int = Field(default=2, ge=0, description="Rewrites of a story that fails checks.")
    staging: Literal["sheet", "coder"] = Field(
        default="sheet",
        description="sheet: a model fills a sheet and a program writes the scene; coder: a "
        "model writes the scene code. A beat whose sheet fails goes to the coder.",
    )
    rounds: int = Field(default=4, ge=1, description="Rounds of a scene before the fallback.")
    retakes: int = Field(default=2, ge=0, description="Retakes of a beat the narrator misread.")
    variants: int = Field(default=1, ge=1, le=5, description="Scenes the coder writes at first.")
    tries: int = Field(default=3, ge=1, description="Failed steps before a job is failed.")
    workers: int = Field(default=0, ge=0, description="Beats rendered at once; 0 is every core.")
    min_free_gb: float = Field(default=2.0, ge=0)

    def reader(self) -> str:
        """The address of the service that reads aloud, when it is not the speech service."""
        return self.voice_url if self.tts == "chatterbox" else ""

    def cores(self) -> int:
        return self.workers or os.cpu_count() or 1
