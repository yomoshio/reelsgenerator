"""Style templates: what makes one channel look and sound different from another.

A style is a TOML file in styles/: the writer's brief, the look of the frames, how captions
and on-screen plates are drawn, and which plates the writer may use."""

import re
import tomllib
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator

from reelsmith.models import Script, StageError

Hex = Annotated[str, StringConstraints(pattern=r"^[0-9A-Fa-f]{6}$")]


class Story(BaseModel):
    brief: str = Field(description="Prose for the writer: structure, voice, what to avoid.")
    critic: str = Field(default="", description="Extra criteria for the script critic.")
    shots: tuple[int, int] = (6, 9)
    beats: tuple[int, int] = Field(default=(8, 12), description="Beats in the episode outline.")
    seconds: tuple[int, int] = (30, 50)
    words: int = Field(default=18, ge=4, description="Most words the narrator says in a shot.")
    empty_shots: int = Field(
        default=2, ge=1, description="Most shots in a row with nobody in the frame."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if any(low > high for low, high in (self.shots, self.beats, self.seconds)):
            raise ValueError("ranges are written low first")
        return self


class Look(BaseModel):
    frame: str = Field(description="Appended to every image prompt.")
    motion: str = Field(default="", description="Appended to every motion prompt.")
    judge: str = Field(description="What the judge should expect the pictures to look like.")


class Captions(BaseModel):
    font: str = "Montserrat ExtraBold"
    size: int = 92
    margin_v: int = Field(default=620, description="Distance of the text from the bottom edge.")
    words: int = Field(default=3, ge=1, le=6)
    spoken: Hex = "FFFFFF"
    upcoming: Hex = "FFFFFF"
    accent: Hex = "FFD21F"
    outline: Hex = "000000"
    outline_px: int = 6
    karaoke: bool = Field(
        default=False,
        description="The word being spoken shows in `accent`, words not yet spoken in `upcoming`.",
    )
    stress_size: int = Field(
        default=115, ge=100, le=160, description="Size of stressed words in karaoke, percent."
    )


class Plate(BaseModel):
    """How one kind of overlay is drawn: a filled box with text, pinned by numpad alignment
    (7 is top left, 9 top right, 4 middle left) and margins in pixels of a 1080x1920 frame."""

    about: str = Field(description="Tells the writer when to use this kind.")
    align: int = Field(default=7, ge=1, le=9)
    margin_l: int = 40
    margin_r: int = 40
    margin_v: int = 70
    size: int = 48
    ink: Hex = "1A1A1A"
    fill: Hex = "FFFFFF"
    pad: int = 16
    upper: bool = True
    number: Hex | None = Field(default=None, description="Colour of a leading `1.` numeral.")
    font: str | None = None


class Style(BaseModel):
    name: str = ""
    about: str = ""
    story: Story
    look: Look
    captions: Captions = Captions()
    overlays: dict[str, Plate] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _plain_kinds(self) -> Self:
        for kind in self.overlays:
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", kind):
                raise ValueError(f"overlay kind {kind!r}: use lowercase letters, digits, - and _")
        return self

    def menu(self) -> str:
        """The overlay kinds as the writer sees them."""
        if not self.overlays:
            return "none: leave `overlays` empty"
        return "\n".join(f"  - `{kind}`: {plate.about}" for kind, plate in self.overlays.items())

    def misfit(self, script: Script) -> str | None:
        """Why the script is outside this style's format, if it is."""
        low, high = self.story.shots
        if not low <= len(script.shots) <= high:
            return f"The script has {len(script.shots)} shots; this channel needs {low} to {high}."
        return None


class Styles:
    """The templates found in one folder, read on first use."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._loaded: dict[str, Style] = {}

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.toml"))

    def get(self, name: str) -> Style:
        if name not in self._loaded:
            self._loaded[name] = self._read(name)
        return self._loaded[name]

    def _read(self, name: str) -> Style:
        path = self.folder / f"{name}.toml"
        if not path.exists():
            have = ", ".join(self.names()) or "none"
            raise StageError(f"no style named {name!r} in {self.folder}; have: {have}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            return Style.model_validate({**raw, "name": name})
        except (tomllib.TOMLDecodeError, ValidationError) as exc:
            raise StageError(f"style {name!r} is broken: {exc}") from exc
