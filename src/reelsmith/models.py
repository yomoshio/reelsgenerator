"""What the conveyor moves: a job, its script, its files and its bill. No I/O here."""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

SHOT_PADDING = 0.35  # breath after each line so cuts do not clip the last syllable
SHOT_MIN, SHOT_MAX = 2.0, 8.0


def required(*names: str) -> ConfigDict:
    """Fields the model must write although a stored record may lack them: the schema the
    model fills lists them as required, while loading an older record falls back to the
    default."""

    def extra(schema: dict[str, Any]) -> None:
        schema["required"] = [*schema.get("required", []), *names]

    return ConfigDict(json_schema_extra=extra)


def shot_seconds(spoken: float, padding: float = SHOT_PADDING) -> float:
    """How long a shot is held for a line that takes `spoken` seconds to say."""
    return min(max(spoken + padding, SHOT_MIN), SHOT_MAX)


class Status(enum.StrEnum):
    NEW = "new"
    SCRIPTED = "scripted"
    VOICED = "voiced"
    PAINTED = "painted"
    FRAMED = "framed"
    ANIMATED = "animated"
    CHECKED = "checked"
    SCORED = "scored"
    ASSEMBLED = "assembled"
    APPROVED = "approved"
    PUBLISHED = "published"
    MEASURED = "measured"
    FAILED = "failed"

    def next(self) -> Status:
        if self in (Status.MEASURED, Status.FAILED):
            raise ValueError(f"{self.value} is terminal")
        return _ORDER[_ORDER.index(self) + 1]

    def before(self, other: Status) -> bool:
        return _ORDER.index(self) < _ORDER.index(other)


# ASSEMBLED -> APPROVED is a human decision, so the conveyor never takes that step itself.
_ORDER: list[Status] = [s for s in Status if s is not Status.FAILED]
GOOD = frozenset({Status.APPROVED, Status.PUBLISHED, Status.MEASURED})


class Recipe(BaseModel):
    """Which models draw and animate this job and which style template shapes it. The first
    `hook_shots` shots go to `hook_video`; after that, shots where nothing moves go to
    `calm_video` and the rest to `video`."""

    style: str = "noir"
    image: str = "z-image"
    video: str = "wan-2.2"
    hook_video: str | None = None
    hook_shots: int = 2
    calm_video: str | None = None
    cast_image: str | None = None  # draws shots with a character from that character's portrait

    def video_for(self, shot: int, moves: bool = True) -> str:
        if shot < self.hook_shots and self.hook_video:
            return self.hook_video
        if not moves and self.calm_video:
            return self.calm_video
        return self.video


class Character(BaseModel):
    name: str
    look: str = Field(
        description="Face, age, hair, clothes and shoes of the story's period. Repeated "
        "verbatim in every shot."
    )
    outfits: dict[str, str] = Field(
        default_factory=dict,
        description="Clothes the story itself changes into, by a short name. Usually empty.",
    )

    def dressed(self, outfit: str | None = None) -> str:
        """The look in one of the outfits, or in the look's own clothes."""
        if outfit in self.outfits:
            return f"{self.look}; in this scene wearing {self.outfits[outfit]} instead"
        return self.look


class Place(BaseModel):
    name: str
    look: str = Field(
        description="In English: the period, the kind of place, its light and the things "
        "that stand in it. Repeated verbatim in every shot set there."
    )


class Overlay(BaseModel):
    """A graphic drawn over the picture: a rule banner, a label on an object, a name card."""

    kind: str = Field(description="One of the kinds the style offers.")
    text: str = Field(description="Short text in the narration language; `|` starts a second line.")
    hold: int = Field(default=1, ge=1, le=8, description="Shots it stays up, this one included.")


class Shot(BaseModel):
    model_config = required("place", "continues")

    line: str = Field(description="Voiceover for this shot, one or two short sentences.")
    picture: str = Field(description="What the still frame shows. No camera moves here.")
    motion: str = Field(description="What moves during the shot and how the camera behaves.")
    cast: list[str] = Field(default_factory=list, description="Names of characters in frame.")
    stress: list[str] = Field(
        min_length=1, description="One or two words of `line`, copied exactly, to highlight."
    )
    overlays: list[Overlay] = Field(default_factory=list)
    moves: bool = Field(
        default=False,
        description="True only for an action the video model animates: a body travels or "
        "falls, something bursts, splashes or flies. Without it the shot gets a camera move.",
    )
    wears: dict[str, str] = Field(
        default_factory=dict,
        description="A character in frame and the outfit they wear here; others wear their look.",
    )
    place: str = Field(default="", description="The name of the place the shot is set in.")
    continues: bool = Field(
        default=False,
        description="The shot goes on from the one before in one take: its clip starts "
        "from the last frame of that shot's clip, and nothing is drawn for it.",
    )
    role: Literal["event", "breath"] = Field(
        default="event",
        description="`event` moves the story on; `breath` lets the event before it land.",
    )
    # Set by the voice stage, never by the writer: a model shown this field filled it with inf.
    seconds: SkipJsonSchema[float] = Field(default=4.0, ge=2.0, le=8.0)


class Script(BaseModel):
    model_config = required("places")

    title: str
    hook: str = Field(description="What the viewer sees and hears in the first two seconds.")
    hook_kind: str = Field(description="One word: question, threat, promise, secret, countdown.")
    characters: list[Character]
    places: list[Place] = Field(default_factory=list, description="Copied from the outline.")
    shots: list[Shot] = Field(min_length=3, max_length=40)
    music: str = Field(description="Genre, tempo and mood for the background track.")

    def looks_of(self, names: Iterable[str], wears: Mapping[str, str] | None = None) -> str:
        wanted, wears = set(names), wears or {}
        return " ".join(c.dressed(wears.get(c.name)) for c in self.characters if c.name in wanted)

    def character(self, name: str) -> Character:
        return next(c for c in self.characters if c.name == name)

    def continued(self, i: int) -> bool:
        """Whether shot `i` is animated on from the shot before instead of from a picture."""
        return 0 < i < len(self.shots) and self.shots[i].continues

    def take(self, i: int) -> list[int]:
        """Shot `i` and the shots that continue it, which all start from its clip."""
        end = i + 1
        while self.continued(end):
            end += 1
        return list(range(i, end))

    def setting(self, shot: Shot) -> str:
        """The look of the place the shot is set in, or nothing for a place not listed."""
        return next((p.look for p in self.places if p.name == shot.place), "")

    @property
    def seconds(self) -> float:
        return sum(s.seconds for s in self.shots)


class Outline(BaseModel):
    """The episode before it becomes shots: what it is about, who is in it, where it
    happens, what happens beat by beat, and the whole voiceover told as one story."""

    model_config = required("premise", "places", "narration")

    title: str
    premise: str = Field(
        default="", description="What the story is about: the thought the ending leaves."
    )
    characters: list[Character] = Field(min_length=1, max_length=4)
    places: list[Place] = Field(default_factory=list, max_length=5)
    beats: list[str] = Field(
        min_length=4, max_length=16, description="One concrete event each, in order."
    )
    planted: str = Field(description="The small detail shown early that the ending brings back.")
    ending: str = Field(description="The last line of the episode, a statement.")
    narration: str = Field(default="", description="The whole voiceover, told as one story.")

    def as_brief(self) -> str:
        """The outline as the writer and the critic read it."""
        people = "; ".join(f"{c.name}: {c.look}" for c in self.characters)
        places = "; ".join(f"{p.name}: {p.look}" for p in self.places)
        beats = " ".join(f"{n}) {beat}" for n, beat in enumerate(self.beats, 1))
        parts = [
            f"{self.title}.",
            f"Premise: {self.premise}" if self.premise else "",
            f"Characters: {people}.",
            f"Places: {places}." if places else "",
            f"Beats: {beats}",
            f"Planted detail: {self.planted}",
            f"Last line: {self.ending}",
            f"Narration, to be cut into shots word for word: {self.narration}"
            if self.narration
            else "",
        ]
        return " ".join(p for p in parts if p)


class EpisodeIdea(BaseModel):
    title: str
    logline: str = Field(description="Goal, obstacle, who is new, the hook in the last line.")


class Season(BaseModel):
    """A serial before its episodes are outlined: the world, the people and the arc."""

    title: str
    world: str
    characters: list[Character] = Field(min_length=1, max_length=6)
    episodes: list[EpisodeIdea] = Field(min_length=1, max_length=30)


class Retelling(BaseModel):
    """A passage of a book as the events that happen in it."""

    events: list[str] = Field(min_length=1, description="Every event of the passage, in order.")


class Part(BaseModel):
    title: str
    logline: str = Field(description="What happens in the episode and where it stops.")
    last: int = Field(ge=1, description="The number of the last event this episode retells.")


class Adaptation(BaseModel):
    """A finished story split into episodes where it turns, before they are outlined."""

    title: str
    world: str
    characters: list[Character] = Field(min_length=1, max_length=6)
    parts: list[Part] = Field(min_length=1, max_length=30)


class Verdict(BaseModel):
    score: float = Field(ge=0, le=10)
    notes: str = ""
    bad_shots: list[int] = Field(default_factory=list)


class Outcome(enum.StrEnum):
    OK = "ok"
    FLAGGED = "flagged"
    FAILED = "failed"


class Call(BaseModel):
    """One call to a model, priced at the tariff of the moment."""

    stage: str
    provider: str
    units: float
    usd: float
    outcome: Outcome = Outcome.OK
    shot: int | None = None
    seconds: float = 0.0
    shared: bool = False


class Metrics(BaseModel):
    views: int
    retention_3s: float = Field(ge=0, le=1)
    completion: float = Field(ge=0, le=1)


class Post(BaseModel):
    caption: str
    hook_kind: str
    ai_generated: bool = True


class Assets(BaseModel):
    """Paths relative to the media root, keyed by shot index where it applies."""

    voices: dict[int, str] = Field(default_factory=dict)
    cast: dict[str, str] = Field(default_factory=dict)
    places: dict[str, str] = Field(default_factory=dict)
    candidates: dict[int, list[str]] = Field(default_factory=dict)
    frames: dict[int, str] = Field(default_factory=dict)
    clips: dict[int, str] = Field(default_factory=dict)
    music: str | None = None
    final: str | None = None
    posted: str | None = None


@dataclass(slots=True)
class Job:
    id: UUID
    idea: str
    status: Status
    recipe: Recipe
    attempts: int = 0
    last_error: str | None = None
    outline: Outline | None = None
    script: Script | None = None
    critique: Verdict | None = None
    qa: Verdict | None = None
    assets: Assets = field(default_factory=Assets)
    calls: list[Call] = field(default_factory=list)
    experiment: str | None = None
    arm: str | None = None
    parent: UUID | None = None
    rating: int | None = None
    metrics: Metrics | None = None

    @classmethod
    def new(
        cls,
        idea: str,
        recipe: Recipe | None = None,
        *,
        experiment: str | None = None,
        arm: str | None = None,
    ) -> Job:
        return cls(uuid4(), idea, Status.NEW, recipe or Recipe(), experiment=experiment, arm=arm)

    def require_script(self) -> Script:
        if self.script is None:
            raise LookupError(f"job {self.id} reached {self.status} without a script")
        return self.script

    @property
    def cost(self) -> float:
        return sum(c.usd for c in self.calls)

    @property
    def spent(self) -> float:
        return sum(c.usd for c in self.calls if not c.shared)

    @property
    def good(self) -> bool:
        return self.status in GOOD

    def fail(self, reason: str, max_attempts: int) -> None:
        self._attempt(reason, max_attempts)

    def rewind(self, to: Status, reason: str, max_attempts: int) -> None:
        if not self._attempt(reason, max_attempts):
            self.status = to

    def reject(self, reason: str, max_attempts: int) -> None:
        """A person turned the cut down: the clips are redone, like after a failed QA."""
        self.assets.clips.clear()
        self.assets.final = None
        self.rewind(Status.FRAMED, reason, max_attempts)

    def _attempt(self, reason: str, max_attempts: int) -> bool:
        self.attempts += 1
        self.last_error = reason
        parked = self.attempts >= max_attempts
        if parked:
            self.status = Status.FAILED
        return parked

    def fork(self, recipe: Recipe, arm: str, *, parent_arm: str = "A") -> Job:
        """Another arm on the same script, voices and frames. Labels the parent too."""
        self.experiment = self.experiment or str(self.id)
        self.arm = self.arm or parent_arm
        status = self.status if self.status.before(Status.FRAMED) else Status.FRAMED
        assets = Assets(
            voices=dict(self.assets.voices),
            candidates={i: list(c) for i, c in self.assets.candidates.items()},
            frames=dict(self.assets.frames),
        )
        return replace(
            self,
            id=uuid4(),
            status=status,
            recipe=recipe,
            attempts=0,
            last_error=None,
            script=self.script.model_copy(deep=True) if self.script else None,
            critique=self.critique.model_copy() if self.critique else None,
            qa=None,
            assets=assets,
            calls=[c.model_copy(update={"shared": True}) for c in self.calls],
            arm=arm,
            parent=self.id,
            rating=None,
            metrics=None,
        )


class StageError(Exception):
    """A job-level failure: the job is retried or parked, the worker keeps running."""


class Rewind(Exception):
    """A gate sends the job back to an earlier status; the conveyor counts it as an attempt."""

    def __init__(self, to: Status, reason: str) -> None:
        super().__init__(reason)
        self.to = to
        self.reason = reason
