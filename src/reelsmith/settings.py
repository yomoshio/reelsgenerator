from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from reelsmith.models import Recipe
from reelsmith.pipeline import Gates
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

    style: str = "noir"
    image_model: str = "z-image"
    video_model: str = "wan-2.2"
    hook_video_model: str | None = None
    calm_video_model: str | None = None
    cast_image_model: str | None = None
    hook_shots: int = 2
    gpu_hour_usd: float = 0.99

    frame_width: int = Field(default=720, multiple_of=16)
    frame_height: int = Field(default=1280, multiple_of=16)
    frame_steps: int = Field(default=8, ge=1)
    edit_steps: int = Field(default=20, ge=1)
    clip_width: int = Field(default=480, multiple_of=16)
    clip_height: int = Field(default=848, multiple_of=16)
    clip_steps: int = Field(default=4, ge=2)
    clip_seconds: float = Field(default=5.0, gt=0, le=10)
    music_steps: int = Field(default=8, ge=1)
    music_level: float = Field(default=0.22, ge=0, le=1)
    voice_cfg: float = Field(default=2.0, gt=0)
    voice_steps: int = Field(default=10, ge=1)
    writer_temperature: float = Field(default=0.8, ge=0, le=2)
    critic_temperature: float = Field(default=0.2, ge=0, le=2)
    judge_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_context: int = Field(default=12288, ge=4096)
    judge_width: int = Field(default=540, ge=256, multiple_of=2)

    script_pass: float = Field(default=7.0, ge=0, le=10)
    clip_pass: float = Field(default=6.0, ge=0, le=10)
    qa_pass: float = Field(default=7.0, ge=0, le=10)
    rewrites: int = Field(default=2, ge=0)
    candidates: int = Field(default=2, ge=1)
    clip_tries: int = Field(default=3, ge=1)

    media_root: Path = Path("/data/media")
    outbox: Path = Path("/data/outbox")
    workflows: Path = Path("/app/workflows")
    styles: Path = Path("/app/styles")
    studio: Path = Path("/data/studio")

    batch_size: int = 6
    gpu_shared: bool = False
    max_attempts: int = 5
    lease_minutes: int = Field(default=3, ge=1)
    idle_seconds: float = 20.0

    def recipe(self) -> Recipe:
        return Recipe(
            style=self.style,
            image=self.image_model,
            video=self.video_model,
            hook_video=self.hook_video_model,
            hook_shots=self.hook_shots,
            calm_video=self.calm_video_model,
            cast_image=self.cast_image_model,
        )

    def gates(self) -> Gates:
        return Gates(
            script_pass=self.script_pass,
            clip_pass=self.clip_pass,
            qa_pass=self.qa_pass,
            rewrites=self.rewrites,
            candidates=self.candidates,
            clip_tries=self.clip_tries,
        )

    def tariff(self) -> Tariff:
        return Tariff(RATES, usd_per_gpu_hour=self.gpu_hour_usd)
