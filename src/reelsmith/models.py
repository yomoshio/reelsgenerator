"""What the conveyor moves: a job, its script, its files and its bill. No I/O here."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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
    """Which models draw and animate this job. The first `hook_shots` shots go to
    `hook_video`, the rest to `video`."""

    image: str = "z-image"
    video: str = "wan-2.2"
    hook_video: str | None = None
    hook_shots: int = 2

    def video_for(self, shot: int) -> str:
        if shot < self.hook_shots and self.hook_video:
            return self.hook_video
        return self.video


class Character(BaseModel):
    name: str
    look: str = Field(description="Face, age, hair, clothes. Repeated verbatim in every shot.")


class Shot(BaseModel):
    line: str = Field(description="Voiceover for this shot, one or two short sentences.")
    picture: str = Field(description="What the still frame shows. No camera moves here.")
    motion: str = Field(description="What moves during the shot and how the camera behaves.")
    cast: list[str] = Field(default_factory=list, description="Names of characters in frame.")
    seconds: float = Field(default=4.0, ge=2.0, le=8.0)


class Script(BaseModel):
    title: str
    hook: str = Field(description="What the viewer sees and hears in the first two seconds.")
    hook_kind: str = Field(description="One word: question, threat, promise, secret, countdown.")
    characters: list[Character]
    shots: list[Shot] = Field(min_length=3, max_length=10)
    music: str = Field(description="Genre, tempo and mood for the background track.")

    def looks_of(self, shot: Shot) -> str:
        wanted = set(shot.cast)
        return " ".join(c.look for c in self.characters if c.name in wanted)

    @property
    def seconds(self) -> float:
        return sum(s.seconds for s in self.shots)


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
