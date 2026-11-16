"""Styles: what makes one channel look and sound different from another. A style is a folder
in styles/ with a `style.toml`: the story rules and brief, the director's brief, the
palette and fonts the runtime draws with, how captions look, the narrator and the music.
Sound files the style names live in the same folder."""

import tomllib
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator

Hex = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
PALETTE_KEYS = (
    "night",
    "wall",
    "floor",
    "line",
    "light",
    "ink",
    "neutral",
    "threat",
    "key",
    "solved",
)


class StyleError(Exception):
    pass


class StoryRules(BaseModel):
    brief: str = Field(description="Prose for the planner: structure, voice, what to avoid.")
    seconds: tuple[int, int] = (60, 95)
    beats: tuple[int, int] = (9, 16)
    words: int = Field(default=14, ge=4, description="Most words in one line of a beat.")
    rules: tuple[int, int] = Field(
        default=(0, 0), description="Numbered rule cards an episode has; (0, 0) means none."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if any(low > high for low, high in (self.seconds, self.beats, self.rules)):
            raise ValueError("ranges are written low first")
        return self

    def narration_words(self) -> tuple[int, int]:
        """How many words a voiceover of this length holds: the narrator says about 2.4
        words a second, pauses included, and the top is kept a little under that."""
        return round(self.seconds[0] * 2.4), round(self.seconds[1] * 2.3)


class Fonts(BaseModel):
    plate: str = Field(description="A font file the runtime draws plates with.")
    caption: str = Field(default="Montserrat ExtraBold", description="A font name for ffmpeg.")


class Captions(BaseModel):
    size: int = 110
    margin_v: int = Field(default=460, description="Distance of the text from the bottom edge.")
    words: int = Field(default=3, ge=1, le=6)
    spoken: Hex = "#FFFFFF"
    upcoming: Hex = "#8E8E93"
    accent: Hex = "#FFD21F"
    outline: Hex = "#000000"
    outline_px: int = 7
    stress_size: int = Field(default=115, ge=100, le=160)


class Voice(BaseModel):
    name: str = Field(default="narrator", description="The speech service's voices/NAME.wav.")
    about: str = Field(description="How the narrator sounds; used to design the voice.")


class Style(BaseModel):
    name: str = ""
    about: str
    story: StoryRules
    director: str = Field(description="Prose for the director: how scenes of this channel look.")
    palette: dict[str, Hex]
    fonts: Fonts
    captions: Captions = Captions()
    voice: Voice
    music: str = Field(default="", description="A music file in the style folder, or none.")
    bed: str = Field(default="", description="A background drone file in the style folder.")
    folder: Path = Path()

    @model_validator(mode="after")
    def _full_palette(self) -> Self:
        missing = [k for k in PALETTE_KEYS if k not in self.palette]
        if missing:
            raise ValueError(f"palette misses {', '.join(missing)}")
        return self

    def file(self, name: str) -> Path | None:
        """A file the style names, if it names one and it is there."""
        path = self.folder / name if name else None
        return path if path and path.is_file() else None


class Styles:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def names(self) -> list[str]:
        return sorted(p.parent.name for p in self.folder.glob("*/style.toml"))

    def get(self, name: str) -> Style:
        path = self.folder / name / "style.toml"
        if not path.is_file():
            known = ", ".join(self.names()) or "none"
            raise StyleError(f"no style {name!r} in {self.folder}; known: {known}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            return Style.model_validate({**raw, "name": name, "folder": path.parent})
        except (tomllib.TOMLDecodeError, ValidationError) as exc:
            raise StyleError(f"{path}: {exc}") from exc
