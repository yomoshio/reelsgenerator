from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from reelsmith.models import Recipe
from reelsmith.pricing import RATES, Tariff


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REELSMITH_", env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    database_url: str = "postgresql://reelsmith:reelsmith@db:5432/reelsmith"
    ollama_url: str = "http://llm:11434"
    comfy_url: str = "http://comfy:8188"
    tts_url: str = "http://tts:8000"

    services: Literal["local", "synthetic"] = "local"
    writer_model: str = "qwen3.5:27b"
    judge_model: str = "qwen3.5:27b"
    language: str = "ru"
    voice: str = "narrator"
    whisper_model: str = "large-v3-turbo"

    image_model: str = "z-image"
    video_model: str = "wan-2.2"
    hook_video_model: str | None = None
    hook_shots: int = 2
    gpu_hour_usd: float = 0.99

    media_root: Path = Path("/data/media")
    outbox: Path = Path("/data/outbox")
    workflows: Path = Path("/app/workflows")

    batch_size: int = 6
    max_attempts: int = 5
    lease_minutes: int = 45
    idle_seconds: float = 20.0

    def recipe(self) -> Recipe:
        return Recipe(
            image=self.image_model,
            video=self.video_model,
            hook_video=self.hook_video_model,
            hook_shots=self.hook_shots,
        )

    def tariff(self) -> Tariff:
        return Tariff(RATES, usd_per_gpu_hour=self.gpu_hour_usd)
