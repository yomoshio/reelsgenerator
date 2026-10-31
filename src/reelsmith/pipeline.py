"""The stations of the conveyor, in order, and what each one needs from outside.

Every stage talks to one GPU service, so the conveyor can hold the card for it. That is
why the judge (Ollama) gets stages of its own, `pick` and `check`, between the ComfyUI
ones instead of being called in the middle of them."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from reelsmith.models import (
    Call,
    Job,
    Metrics,
    Outcome,
    Post,
    Recipe,
    Rewind,
    Script,
    StageError,
    Status,
    Verdict,
)
from reelsmith.pricing import Tariff, metered
from reelsmith.services.ffmpeg import Cut, Segment, Word, captions, shift, to_ass

FRAME_STYLE = "vertical 9:16 film still, natural light, shallow depth of field, 35mm grain"
SHOT_PADDING = 0.35  # breath after each line so cuts do not clip the last syllable
SHOT_MIN, SHOT_MAX = 2.0, 8.0
SCRIPT_PASS, CLIP_PASS, QA_PASS = 7.0, 6.0, 7.0
REWRITES = 2  # script rewrites after a failed critique
CANDIDATES = 2  # frames painted per shot
CLIP_TRIES = 3  # animations of one shot before its last clip is kept whatever the judge says
STILLS, QA_STILLS = 4, 8


# What a stage may ask for. Real implementations live in services/, stand-ins in
# services/synthetic.py, and tests/fakes.py has the scripted ones.


class Llm(Protocol):
    name: str

    async def write(self, idea: str, notes: str | None = None) -> Script: ...

    async def review(self, script: Script) -> Verdict: ...

    async def pick(self, brief: str, images: list[Path]) -> int: ...

    async def inspect(self, motion: str, stills: list[Path]) -> Verdict: ...

    async def judge(self, script: Script, stills: list[Path]) -> Verdict: ...


class Painter(Protocol):
    name: str

    async def paint(self, prompt: str, *, seed: int, out: Path) -> Path: ...


class Animator(Protocol):
    name: str
    max_seconds: float

    def length(self, seconds: float) -> float:
        """Seconds the model will generate, and be billed for, for a request of `seconds`."""
        ...

    async def animate(
        self, frame: Path, motion: str, *, seconds: float, seed: int, out: Path
    ) -> Path: ...


class Narrator(Protocol):
    name: str
    suffix: str

    async def speak(self, text: str, out: Path) -> Path: ...


class Composer(Protocol):
    name: str
    suffix: str

    async def compose(self, brief: str, *, seconds: float, seed: int, out: Path) -> Path: ...


class Transcriber(Protocol):
    async def words(self, audio: Path) -> list[Word]: ...


class Montage(Protocol):
    async def seconds(self, media: Path) -> float: ...

    async def stills(self, video: Path, count: int, out_dir: Path) -> list[Path]: ...

    async def render(self, cut: Cut, out: Path) -> Path: ...


class Publisher(Protocol):
    async def publish(self, video: Path, post: Post) -> str: ...


class Analytics(Protocol):
    async def measure(self, posted: str) -> Metrics: ...


@dataclass(frozen=True)
class Services:
    """Everything the stages talk to. `app.py` builds the local set or the synthetic one."""

    llm: Llm
    painters: Mapping[str, Painter]
    animators: Mapping[str, Animator]
    narrator: Narrator
    composer: Composer
    transcriber: Transcriber
    montage: Montage
    publisher: Publisher
    tariff: Tariff
    media: Path
    analytics: Analytics | None = None

    def painter(self, name: str) -> Painter:
        return _named(self.painters, name, "image")

    def animator(self, name: str) -> Animator:
        return _named(self.animators, name, "video")

    def check(self, recipe: Recipe) -> None:
        self.painter(recipe.image)
        for shot in (0, recipe.hook_shots):
            self.animator(recipe.video_for(shot))


def _named[T](table: Mapping[str, T], name: str, role: str) -> T:
    try:
        return table[name]
    except KeyError:
        have = ", ".join(sorted(table)) or "none"
        raise StageError(f"no {role} model named {name!r}; have: {have}") from None


@dataclass(frozen=True, slots=True)
class Files:
    """Where a job keeps its files. Stored paths are relative so the volume can move."""

    root: Path
    job_id: UUID

    @property
    def base(self) -> Path:
        return self.root / str(self.job_id)

    def voice(self, shot: int, suffix: str = ".wav") -> Path:
        return self._file(f"voice/{shot:02d}{suffix}")

    def frame(self, shot: int, candidate: int = 0) -> Path:
        return self._file(f"frames/{shot:02d}-{candidate}.png")

    def clip(self, shot: int) -> Path:
        return self._file(f"clips/{shot:02d}.mp4")

    def stills(self, shot: int | None) -> Path:
        name = "final" if shot is None else f"{shot:02d}"
        path = self.base / "stills" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def music(self, suffix: str = ".flac") -> Path:
        return self._file(f"music{suffix}")

    def subtitles(self) -> Path:
        return self._file("subtitles.ass")

    def final(self) -> Path:
        return self._file("final.mp4")

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def resolve(self, stored: str) -> Path:
        return self.root / stored

    def _file(self, name: str) -> Path:
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def seed_for(job_id: UUID, salt: int = 0) -> int:
    """Same job, same seed: a retried stage redraws the same picture."""
    return (int.from_bytes(job_id.bytes[:4], "big") + salt) % 2**31


# The stages. Each reads what earlier ones left on the job and adds its part.


async def write(job: Job, s: Services) -> None:
    """Writer and critic go round until the script scores 7 or the rewrites are spent.
    The best draft is kept either way: the gate is advisory, the report shows it."""
    best: tuple[Script, Verdict] | None = None
    notes: str | None = None
    for _ in range(REWRITES + 1):
        with metered(job, s.tariff, stage="script", provider=s.llm.name):
            script = await s.llm.write(job.idea, notes)
        with metered(job, s.tariff, stage="critic", provider=s.llm.name):
            verdict = await s.llm.review(script)
        if best is None or verdict.score > best[1].score:
            best = (script, verdict)
        if verdict.score >= SCRIPT_PASS:
            break
        notes = verdict.notes
    if best is not None:
        job.script, job.critique = best


async def voice(job: Job, s: Services) -> None:
    """Before pictures on purpose: the spoken line decides how long its shot lasts."""
    script, files = job.require_script(), Files(s.media, job.id)
    for i, shot in enumerate(script.shots):
        with metered(
            job, s.tariff, stage="voice", provider=s.narrator.name, units=len(shot.line), shot=i
        ):
            audio = await s.narrator.speak(shot.line, files.voice(i, s.narrator.suffix))
        spoken = await s.montage.seconds(audio)
        shot.seconds = min(max(spoken + SHOT_PADDING, SHOT_MIN), SHOT_MAX)
        job.assets.voices[i] = files.relative(audio)


async def paint(job: Job, s: Services) -> None:
    """Two candidate frames per shot; `pick` chooses between them in the next stage."""
    script, files = job.require_script(), Files(s.media, job.id)
    painter = s.painter(job.recipe.image)
    for i, shot in enumerate(script.shots):
        if i in job.assets.candidates:
            continue
        prompt = ". ".join(p for p in (script.looks_of(shot), shot.picture, FRAME_STYLE) if p)
        made: list[Path] = []
        for k in range(CANDIDATES):
            seed = seed_for(job.id, 1000 + i * 10 + k)
            with metered(job, s.tariff, stage="frame", provider=painter.name, shot=i):
                made.append(await painter.paint(prompt, seed=seed, out=files.frame(i, k)))
        job.assets.candidates[i] = [files.relative(p) for p in made]


async def pick(job: Job, s: Services) -> None:
    script, files = job.require_script(), Files(s.media, job.id)
    for i, shot in enumerate(script.shots):
        if i in job.assets.frames:
            continue
        images = [files.resolve(p) for p in job.assets.candidates[i]]
        with metered(job, s.tariff, stage="pick", provider=s.llm.name, shot=i):
            chosen = await s.llm.pick(shot.picture, images)
        job.assets.frames[i] = job.assets.candidates[i][chosen]


async def animate(job: Job, s: Services) -> None:
    """One clip per shot from its chosen frame. Shots that already have a clip are skipped,
    so a rewind redoes only what `check` or QA threw away; the seed moves with the attempt."""
    script, files = job.require_script(), Files(s.media, job.id)
    for i, shot in enumerate(script.shots):
        if i in job.assets.clips:
            continue
        animator = s.animator(job.recipe.video_for(i))
        seconds = min(shot.seconds, animator.max_seconds)
        seed = seed_for(job.id, 2000 + i * 10 + job.attempts)
        with metered(
            job,
            s.tariff,
            stage="animate",
            provider=animator.name,
            units=animator.length(seconds),
            shot=i,
        ):
            clip = await animator.animate(
                files.resolve(job.assets.frames[i]),
                shot.motion,
                seconds=seconds,
                seed=seed,
                out=files.clip(i),
            )
        job.assets.clips[i] = files.relative(clip)


async def check(job: Job, s: Services) -> None:
    """The judge looks at four stills of every clip. A flagged clip is dropped and the job
    goes back to `animate`, unless that shot has had its tries: then the clip stays."""
    script, files = job.require_script(), Files(s.media, job.id)
    redo: list[int] = []
    for i, shot in enumerate(script.shots):
        stills = await s.montage.stills(files.resolve(job.assets.clips[i]), STILLS, files.stills(i))
        with metered(job, s.tariff, stage="inspect", provider=s.llm.name, shot=i):
            verdict = await s.llm.inspect(shot.motion, stills)
        if verdict.score >= CLIP_PASS:
            continue
        made = _animations(job, i)
        made[-1].outcome = Outcome.FLAGGED
        if len(made) < CLIP_TRIES:
            redo.append(i)
    for i in redo:
        del job.assets.clips[i]
    if redo:
        raise Rewind(Status.FRAMED, f"clips flagged for shots {redo}")


def _animations(job: Job, shot: int) -> list[Call]:
    return [c for c in job.calls if c.stage == "animate" and c.shot == shot and not c.shared]


async def score(job: Job, s: Services) -> None:
    if job.assets.music is not None:
        return
    script, files = job.require_script(), Files(s.media, job.id)
    seconds = script.seconds + 2
    with metered(job, s.tariff, stage="music", provider=s.composer.name, units=seconds):
        track = await s.composer.compose(
            script.music, seconds=seconds, seed=seed_for(job.id), out=files.music(s.composer.suffix)
        )
    job.assets.music = files.relative(track)


async def assemble(job: Job, s: Services) -> None:
    """Cuts the clips to their lines, mixes voice over music, burns subtitles, then shows
    the judge eight stills of the result. A failed QA drops the bad clips and rewinds."""
    script, files = job.require_script(), Files(s.media, job.id)
    if job.assets.music is None:
        raise LookupError(f"job {job.id} reached assembly without music")

    segments: list[Segment] = []
    words: list[Word] = []
    start = 0.0
    for i, shot in enumerate(script.shots):
        voice = files.resolve(job.assets.voices[i])
        words += shift(await s.transcriber.words(voice), start)
        segments.append(Segment(files.resolve(job.assets.clips[i]), voice, shot.seconds))
        start += shot.seconds

    subtitles = files.subtitles()
    subtitles.write_text(to_ass(captions(words)), encoding="utf-8")
    cut = Cut(tuple(segments), files.resolve(job.assets.music), subtitles)
    final = await s.montage.render(cut, files.final())
    job.assets.final = files.relative(final)

    stills = await s.montage.stills(final, QA_STILLS, files.stills(None))
    with metered(job, s.tariff, stage="qa", provider=s.llm.name):
        verdict = await s.llm.judge(script, stills)
    job.qa = verdict
    if verdict.score < QA_PASS:
        for i in verdict.bad_shots or list(job.assets.clips):
            job.assets.clips.pop(i, None)
        job.assets.final = None
        raise Rewind(Status.FRAMED, verdict.notes or "the cut did not pass QA")


async def publish(job: Job, s: Services) -> None:
    script = job.require_script()
    if job.assets.final is None:
        raise LookupError(f"job {job.id} was approved without a final cut")
    video = Files(s.media, job.id).resolve(job.assets.final)
    post = Post(caption=script.title, hook_kind=script.hook_kind)
    job.assets.posted = await s.publisher.publish(video, post)


async def measure(job: Job, s: Services) -> None:
    """Only where analytics can be read by code; otherwise `reelsmith measure` does this."""
    if s.analytics is None:
        raise StageError("no analytics service; enter the numbers with `reelsmith measure`")
    if job.assets.posted is None:
        raise LookupError(f"job {job.id} was published without a reference")
    job.metrics = await s.analytics.measure(job.assets.posted)


Run = Callable[[Job, Services], Awaitable[None]]


@dataclass(frozen=True)
class Stage:
    name: str
    takes: Status
    gpu: str | None
    run: Run
    settled: timedelta = timedelta(0)


STAGES = [
    Stage("write", Status.NEW, "llm", write),
    Stage("voice", Status.SCRIPTED, "tts", voice),
    Stage("paint", Status.VOICED, "comfy", paint),
    Stage("pick", Status.PAINTED, "llm", pick),
    Stage("animate", Status.FRAMED, "comfy", animate),
    Stage("check", Status.ANIMATED, "llm", check),
    Stage("score", Status.CHECKED, "comfy", score),
    Stage("assemble", Status.SCORED, "llm", assemble),
    Stage("publish", Status.APPROVED, None, publish),
    Stage("measure", Status.PUBLISHED, None, measure, settled=timedelta(hours=24)),
]
