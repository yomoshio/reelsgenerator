"""Scripted stand-ins for tests. They write empty files and remember what they were asked."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reelsmith.models import (
    Character,
    Job,
    Metrics,
    Outline,
    Post,
    Recipe,
    Script,
    Shot,
    Status,
    Verdict,
)
from reelsmith.pipeline import Services
from reelsmith.pricing import Rate, Tariff, Unit
from reelsmith.services.ffmpeg import Cut, Word
from reelsmith.styles import Style, Styles

STYLES = Styles(Path(__file__).parent / "styles")
REPO_STYLES = Path(__file__).parent.parent / "styles"


def style() -> Style:
    return STYLES.get("fake")


def script(shots: int = 3, *, hook_kind: str = "question", title: str = "t") -> Script:
    return Script(
        title=title,
        hook="a door that should be locked",
        hook_kind=hook_kind,
        characters=[Character(name="Vera", look="nurse, 30s, grey cardigan")],
        shots=[
            Shot(
                line=f"line {i}",
                picture=f"picture {i}",
                motion=f"motion {i}",
                cast=["Vera"],
                stress=["none"],
            )
            for i in range(shots)
        ],
        music="slow drone",
    )


def outline(title: str = "zombies") -> Outline:
    return Outline(
        title=title,
        characters=[Character(name="Vera", look="nurse, 30s, grey cardigan")],
        beats=[f"beat {i}" for i in range(6)],
        planted="the logbook",
        ending="the logbook was hers",
    )


def recipe(**overrides: object) -> Recipe:
    return Recipe(**{"style": "fake", "image": "fake", "video": "fast", **overrides})  # type: ignore[arg-type]


def job(
    idea: str = "zombies",
    status: Status = Status.NEW,
    *,
    recipe: Recipe | None = None,
    script: Script | None = None,
) -> Job:
    made = Job.new(idea, recipe or globals()["recipe"]())
    made.status = status
    made.script = script
    return made


def tariff() -> Tariff:
    return Tariff(
        {
            "fake": Rate(Unit.CALL, 36),
            "fast": Rate(Unit.SECOND, 360),
            "slow": Rate(Unit.SECOND, 720),
            "hook": Rate(Unit.SECOND, 1440),
        }
    )


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


@dataclass
class FakeLlm:
    name: str = "fake"
    scores: list[float] = field(default_factory=lambda: [8.0])
    hook_kind: str = "question"
    shots: list[int] = field(default_factory=lambda: [3])
    picks: int = 0
    flag: set[int] = field(default_factory=set)
    reject: Verdict | None = None
    written: list[tuple[str, str | None]] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)
    reviewed_against: list[str] = field(default_factory=list)
    inspected: int = 0
    log: list[tuple[str, list[Path]]] = field(default_factory=list)

    async def plan(self, idea: str, style: Style) -> Outline:
        self.planned.append(idea)
        return outline(idea)

    async def write(self, idea: str, style: Style, notes: str | None = None) -> Script:
        self.written.append((idea, notes))
        count = self.shots.pop(0) if len(self.shots) > 1 else self.shots[0]
        title = f"{idea.split('.', maxsplit=1)[0]} draft {len(self.written)}"
        return script(count, hook_kind=self.hook_kind, title=title)

    async def review(self, script: Script, style: Style, outline: str = "") -> Verdict:
        self.reviewed_against.append(outline)
        score = self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]
        return Verdict(score=score, notes="tighten the hook")

    async def pick(self, brief: str, images: list[Path], style: Style) -> int:
        self.log.append(("pick", images))
        return self.picks

    async def inspect(self, motion: str, stills: list[Path], style: Style) -> Verdict:
        self.log.append(("inspect", stills))
        flagged = self.inspected in self.flag
        self.inspected += 1
        return Verdict(score=4.0 if flagged else 8.0, notes="smear" if flagged else "")

    async def judge(self, script: Script, stills: list[Path], style: Style) -> Verdict:
        self.log.append(("judge", stills))
        return self.reject or Verdict(score=8.5)


@dataclass
class FakePainter:
    name: str = "fake"
    log: list[tuple[str, int]] = field(default_factory=list)

    async def paint(self, prompt: str, *, seed: int, out: Path) -> Path:
        self.log.append((prompt, seed))
        return _touch(out)


@dataclass
class FakeAnimator:
    name: str
    max_seconds: float = 8.0
    log: list[tuple[Path, str, float, int]] = field(default_factory=list)

    def length(self, seconds: float) -> float:
        return seconds

    async def animate(
        self, frame: Path, motion: str, *, seconds: float, seed: int, out: Path
    ) -> Path:
        self.log.append((frame, motion, seconds, seed))
        return _touch(out)


@dataclass
class FakeNarrator:
    suffix: str = ".wav"
    name: str = "fake"
    log: list[str] = field(default_factory=list)
    deliveries: list[str] = field(default_factory=list)

    async def speak(self, text: str, out: Path, delivery: str = "") -> Path:
        self.deliveries.append(delivery)
        self.log.append(text)
        return _touch(out)


@dataclass
class FakeComposer:
    suffix: str = ".flac"
    name: str = "fake"
    log: list[tuple[str, float]] = field(default_factory=list)

    async def compose(self, brief: str, *, seconds: float, seed: int, out: Path) -> Path:
        self.log.append((brief, seconds))
        return _touch(out)


@dataclass
class FakeMontage:
    seconds_per_file: float = 3.0
    rendered: list[Cut] = field(default_factory=list)
    moments: list[float] = field(default_factory=list)

    async def seconds(self, media: Path) -> float:
        return self.seconds_per_file

    async def stills(self, video: Path, count: int, out_dir: Path) -> list[Path]:
        return [_touch(out_dir / f"{i:02d}.png") for i in range(count)]

    async def stills_at(self, video: Path, times: list[float], out_dir: Path) -> list[Path]:
        self.moments = times
        return [_touch(out_dir / f"{i:02d}.png") for i in range(len(times))]

    async def render(self, cut: Cut, out: Path) -> Path:
        self.rendered.append(cut)
        return _touch(out)


@dataclass
@dataclass
class FakeTranscriber:
    heard: list[Word] = field(default_factory=lambda: [Word("line", 0.0, 0.4)])

    async def words(self, audio: Path) -> list[Word]:
        return list(self.heard)


@dataclass
class FakePublisher:
    log: list[Post] = field(default_factory=list)

    async def publish(self, video: Path, post: Post) -> str:
        self.log.append(post)
        return f"posted/{video.parent.name}"


@dataclass
class FakeAnalytics:
    retention: float = 0.5

    async def measure(self, posted: str) -> Metrics:
        return Metrics(views=1000, retention_3s=self.retention, completion=0.3)


def services(
    media: Path,
    *,
    llm: FakeLlm | None = None,
    painter: FakePainter | None = None,
    animators: dict[str, FakeAnimator] | None = None,
    narrator: FakeNarrator | None = None,
    composer: FakeComposer | None = None,
    montage: FakeMontage | None = None,
    transcriber: FakeTranscriber | None = None,
    publisher: FakePublisher | None = None,
    analytics: FakeAnalytics | None = None,
) -> Services:
    return Services(
        llm=llm or FakeLlm(),
        painters={"fake": painter or FakePainter()},
        animators=animators or {"fast": FakeAnimator("fast"), "slow": FakeAnimator("slow")},
        narrator=narrator or FakeNarrator(),
        composer=composer or FakeComposer(),
        transcriber=transcriber or FakeTranscriber(),
        montage=montage or FakeMontage(),
        publisher=publisher or FakePublisher(),
        tariff=tariff(),
        media=media,
        styles=STYLES,
        analytics=analytics,
    )
