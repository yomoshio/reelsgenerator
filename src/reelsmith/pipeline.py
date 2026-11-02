"""The stages of the conveyor in order, and the services they need.

Every stage talks to one GPU service, so the conveyor can hold the card for it. That is
why the judge has stages of its own, `pick` and `check`, between the ComfyUI ones."""

import asyncio
import hashlib
import re
import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol
from uuid import UUID

from reelsmith.checks import bare, present, problems, unsaid_plates
from reelsmith.models import (
    Call,
    Job,
    Metrics,
    Outcome,
    Outline,
    Post,
    Recipe,
    Rewind,
    Script,
    Shot,
    StageError,
    Status,
    Verdict,
)
from reelsmith.pricing import Tariff, metered
from reelsmith.services.ffmpeg import Caption, Card, Cut, Segment, Word, captions, shift, to_ass
from reelsmith.styles import Style, Styles

SHOT_PADDING = 0.35  # breath after each line so cuts do not clip the last syllable
SHOT_MIN, SHOT_MAX = 2.0, 8.0
STILLS = 4  # per clip for the judge


@dataclass(frozen=True)
class Gates:
    """Where the judges draw the line and how often a stage may try again."""

    script_pass: float = 7.0
    clip_pass: float = 6.0
    qa_pass: float = 7.0
    rewrites: int = 2
    candidates: int = 2
    clip_tries: int = 3


class Llm(Protocol):
    name: str

    async def plan(self, idea: str, style: Style) -> Outline: ...

    async def write(self, idea: str, style: Style, notes: str | None = None) -> Script: ...

    async def review(self, script: Script, style: Style, outline: str = "") -> Verdict: ...

    async def pick(self, brief: str, images: list[Path], style: Style) -> int: ...

    async def inspect(self, motion: str, stills: list[Path], style: Style) -> Verdict: ...

    async def judge(self, script: Script, stills: list[Path], style: Style) -> Verdict: ...


class Painter(Protocol):
    name: str

    async def paint(
        self, prompt: str, *, seed: int, out: Path, reference: Path | None = None
    ) -> Path: ...


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

    async def speak(self, text: str, out: Path, delivery: str = "") -> Path: ...


class Composer(Protocol):
    name: str
    suffix: str

    async def compose(self, brief: str, *, seconds: float, seed: int, out: Path) -> Path: ...


class Transcriber(Protocol):
    async def words(self, audio: Path) -> list[Word]: ...


class Montage(Protocol):
    async def seconds(self, media: Path) -> float: ...

    async def stills(self, video: Path, count: int, out_dir: Path) -> list[Path]: ...

    async def stills_at(self, video: Path, times: list[float], out_dir: Path) -> list[Path]: ...

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
    styles: Styles
    analytics: Analytics | None = None
    gates: Gates = Gates()
    showcase: Path | None = None  # a copy of every cut lands here, e.g. ComfyUI's output

    def painter(self, name: str) -> Painter:
        return _named(self.painters, name, "image")

    def animator(self, name: str) -> Animator:
        return _named(self.animators, name, "video")

    def check(self, recipe: Recipe) -> None:
        self.styles.get(recipe.style)
        self.painter(recipe.image)
        if recipe.cast_image:
            self.painter(recipe.cast_image)
        for shot in (0, recipe.hook_shots):
            self.animator(recipe.video_for(shot))
        self.animator(recipe.video_for(recipe.hook_shots, moves=False))


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


async def write(job: Job, s: Services) -> None:
    """The idea, a sentence or a whole story, first becomes a beat-by-beat outline; the
    model follows an outline far better than it invents a plot while writing shots. Then
    writer and critic go round until the script passes or the rewrites are spent. A script
    with a problem `checks` can see cannot pass. The best draft is kept either way."""
    style = s.styles.get(job.recipe.style)
    if job.outline is None:
        with metered(job, s.tariff, stage="plan", provider=s.llm.name):
            job.outline = await s.llm.plan(job.idea, style)
    brief = job.outline.as_brief()
    best: tuple[Script, Verdict] | None = None
    notes: str | None = None
    for _ in range(s.gates.rewrites + 1):
        with metered(job, s.tariff, stage="script", provider=s.llm.name):
            script = await s.llm.write(brief, style, notes)
        with metered(job, s.tariff, stage="critic", provider=s.llm.name):
            verdict = await s.llm.review(script, style, brief)
        if found := problems(script, style):
            verdict = Verdict(
                score=min(verdict.score, s.gates.script_pass - 1),
                notes=" ".join([*found[:6], verdict.notes]),
            )
        if best is None or verdict.score > best[1].score:
            best = (script, verdict)
        if verdict.score >= s.gates.script_pass:
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
            out = files.voice(i, s.narrator.suffix)
            audio = await s.narrator.speak(shot.line, out, delivery=shot.delivery)
        spoken = await s.montage.seconds(audio)
        shot.seconds = min(max(spoken + SHOT_PADDING, SHOT_MIN), SHOT_MAX)
        job.assets.voices[i] = files.relative(audio)


async def paint(job: Job, s: Services) -> None:
    """Candidate frames for every shot; `pick` chooses among them in the next stage. With a
    `cast_image` model, every character first gets a portrait, and shots with a character
    are drawn from the portrait of the first one in frame, so faces and clothes hold."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    painter = s.painter(job.recipe.image)
    portraits = await _portraits(job, s, style) if job.recipe.cast_image else {}
    for i, shot in enumerate(script.shots):
        if i in job.assets.candidates:
            continue
        cast = present(shot, script)
        prompt = ". ".join(p for p in (script.looks_of(cast), shot.picture, style.look.frame) if p)
        lead = next((name for name in cast if name in portraits), None)
        artist, reference = painter, None
        if lead is not None and job.recipe.cast_image:
            artist, reference = s.painter(job.recipe.cast_image), files.resolve(portraits[lead])
            prompt = f"The same person as in the reference image, {lead}. {prompt}"
        made: list[Path] = []
        for k in range(s.gates.candidates):
            seed = seed_for(job.id, 1000 + i * 10 + k)
            with metered(job, s.tariff, stage="frame", provider=artist.name, shot=i):
                out = files.frame(i, k)
                made.append(await artist.paint(prompt, seed=seed, out=out, reference=reference))
        job.assets.candidates[i] = [files.relative(p) for p in made]


async def _portraits(job: Job, s: Services, style: Style) -> dict[str, str]:
    """One full-figure portrait per character. The file is named after the look and the
    style, so the same character described the same way gets the same portrait in every
    episode of a serial, and is painted only once."""
    script, files = job.require_script(), Files(s.media, job.id)
    painter = s.painter(job.recipe.image)
    for character in script.characters:
        if character.name in job.assets.cast:
            continue
        key = hashlib.sha1(f"{style.name}|{character.look}".encode()).hexdigest()[:12]
        portrait = s.media / "cast" / f"{key}.png"
        if not portrait.exists():
            portrait.parent.mkdir(parents=True, exist_ok=True)
            prompt = (
                f"{character.look}. Full figure, standing, facing the viewer, plain background, "
                f"character reference. {style.look.frame}"
            )
            with metered(job, s.tariff, stage="cast", provider=painter.name):
                await painter.paint(prompt, seed=int(key, 16) % 2**31, out=portrait)
        job.assets.cast[character.name] = files.relative(portrait)
    return job.assets.cast


async def pick(job: Job, s: Services) -> None:
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    for i, shot in enumerate(script.shots):
        if i in job.assets.frames:
            continue
        images = [files.resolve(p) for p in job.assets.candidates[i]]
        with metered(job, s.tariff, stage="pick", provider=s.llm.name, shot=i):
            chosen = await s.llm.pick(shot.picture, images, style)
        job.assets.frames[i] = job.assets.candidates[i][chosen]


async def animate(job: Job, s: Services) -> None:
    """One clip per shot from its chosen frame. Shots that already have a clip are skipped,
    so a rewind redoes only what `check` or QA threw away; the seed moves with the attempt."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    for i, shot in enumerate(script.shots):
        if i in job.assets.clips:
            continue
        guard = _nobody_new(present(shot, script))
        motion = ". ".join(m for m in (shot.motion, guard, style.look.motion) if m)
        animator = s.animator(job.recipe.video_for(i, shot.moves))
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
                motion,
                seconds=seconds,
                seed=seed,
                out=files.clip(i),
            )
        job.assets.clips[i] = files.relative(clip)


async def check(job: Job, s: Services) -> None:
    """The judge looks at four stills of every clip it has not seen yet. A flagged clip is
    dropped and the job goes back to `animate`, unless that shot has had its tries: then
    the clip stays. A clip that passed once is not judged again, or a judge that wavers
    would send the job round until it runs out of attempts."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    redo: list[int] = []
    for i, shot in enumerate(script.shots):
        # A camera move over the frame `pick` already chose shows nothing new to judge, and
        # animating it again would show the same frame.
        if _judged(job, i) or job.recipe.video_for(i, shot.moves) == "still":
            continue
        stills = await s.montage.stills(files.resolve(job.assets.clips[i]), STILLS, files.stills(i))
        with metered(job, s.tariff, stage="inspect", provider=s.llm.name, shot=i):
            verdict = await s.llm.inspect(shot.motion, stills, style)
        if verdict.score >= s.gates.clip_pass:
            continue
        made = _animations(job, i)
        made[-1].outcome = Outcome.FLAGGED
        if len(made) < s.gates.clip_tries:
            redo.append(i)
    for i in redo:
        del job.assets.clips[i]
    if redo:
        raise Rewind(Status.FRAMED, f"clips flagged for shots {redo}")


def _animations(job: Job, shot: int) -> list[Call]:
    return [c for c in job.calls if c.stage == "animate" and c.shot == shot and not c.shared]


def _judged(job: Job, shot: int) -> bool:
    """Whether an inspection came after the latest animation of this shot."""
    last = {"animate": -1, "inspect": -1}
    for n, call in enumerate(job.calls):
        if (
            call.shot == shot
            and call.stage in last
            and not (call.shared and call.stage == "animate")
        ):
            last[call.stage] = n
    return last["inspect"] > last["animate"]


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
    the judge one still from the middle of every shot. A failed QA drops the bad clips
    and rewinds."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    if job.assets.music is None:
        raise LookupError(f"job {job.id} reached assembly without music")

    segments: list[Segment] = []
    lines: list[Caption] = []
    starts: list[float] = []
    start = 0.0
    for i, shot in enumerate(script.shots):
        voice = files.resolve(job.assets.voices[i])
        heard = shift(await s.transcriber.words(voice), start)
        spoken = _accented(as_written(heard, shot.line), shot)
        lines += captions(spoken, max_words=style.captions.words)
        segments.append(Segment(files.resolve(job.assets.clips[i]), voice, shot.seconds))
        starts.append(start)
        start += shot.seconds

    subtitles = files.subtitles()
    ass = to_ass(lines, style, _cards(script, style, starts))
    subtitles.write_text(ass, encoding="utf-8")
    cut = Cut(tuple(segments), files.resolve(job.assets.music), subtitles)
    final = await s.montage.render(cut, files.final())
    job.assets.final = files.relative(final)
    if s.showcase is not None:
        s.showcase.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, final, s.showcase / showcase_name(job))

    middles = [start + shot.seconds / 2 for start, shot in zip(starts, script.shots, strict=True)]
    stills = await s.montage.stills_at(final, middles, files.stills(None))
    with metered(job, s.tariff, stage="qa", provider=s.llm.name):
        verdict = await s.llm.judge(script, stills, style)
    verdict.bad_shots = [i for i in verdict.bad_shots if 0 <= i < len(script.shots)]
    job.qa = verdict
    if verdict.score < s.gates.qa_pass:
        for i in verdict.bad_shots or list(job.assets.clips):
            job.assets.clips.pop(i, None)
        job.assets.final = None
        raise Rewind(Status.FRAMED, verdict.notes or "the cut did not pass QA")


def showcase_name(job: Job) -> str:
    """A file name a person recognises: the short id, then the title."""
    title = job.script.title if job.script else job.idea
    slug = re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:40].rstrip("-")
    return f"{job.id.hex[:8]}-{slug or 'video'}.mp4"


def as_written(heard: list[Word], line: str) -> list[Word]:
    """Captions show the line as the writer wrote it, numbers in words and names spelled
    right; the transcript only says when the words are spoken. Words the transcript caught
    keep its timing, pauses included. Words it heard differently, such as «двадцать» heard
    as «20», share the time of what it heard in their place."""
    written = line.split()
    if not heard or not written:
        return heard
    matcher = SequenceMatcher(
        a=[bare(w) for w in written], b=[bare(w.text) for w in heard], autojunk=False
    )
    out: list[Word] = []
    for tag, w1, w2, h1, h2 in matcher.get_opcodes():
        if tag == "insert":
            continue
        if w2 - w1 == h2 - h1:
            pairs = zip(written[w1:w2], heard[h1:h2], strict=True)
            out += [replace(word, text=text) for text, word in pairs]
            continue
        start = heard[h1].start if h2 > h1 else out[-1].end if out else heard[0].start
        end = heard[h2 - 1].end if h2 > h1 else heard[h1].start if h1 < len(heard) else start
        out += _spread(written[w1:w2], start, end)
    return out


def _spread(texts: list[str], start: float, end: float) -> list[Word]:
    """Words laid one after another over a span, each as long as its letters."""
    end = max(end, start + 0.15 * len(texts))
    total = sum(len(t) for t in texts)
    out: list[Word] = []
    at = start
    for text in texts:
        length = (end - start) * len(text) / total
        out.append(Word(text, at, at + length))
        at += length
    return out


def _accented(words: list[Word], shot: Shot) -> list[Word]:
    """Marks the words the writer asked to stress; the style decides how they look."""
    wanted = {bare(w) for phrase in shot.stress for w in phrase.split()}
    return [replace(w, accent=bare(w.text) in wanted) for w in words]


def _nobody_new(people: list[str]) -> str:
    """The video model fills an empty frame with whoever it likes unless told otherwise."""
    if not people:
        return "the place stays empty, no person, animal or creature appears"
    return "only the people already in the frame, nobody new appears"


def _cards(script: Script, style: Style, starts: list[float]) -> list[Card]:
    """Overlays on the timeline: each lasts from its shot through `hold` shots, or until
    the next overlay of its kind comes up, so two rule banners never share a frame. The
    same plate repeated on the next shot stays up instead of popping in again. A plate whose
    words the narrator has not said yet stays off: the viewer would read what they have not
    been told."""
    early = {(i, o.kind, o.text) for i, o in unsaid_plates(script)}
    cards: list[Card] = []
    for i, shot in enumerate(script.shots):
        for overlay in shot.overlays:
            if overlay.kind not in style.overlays or (i, overlay.kind, overlay.text) in early:
                continue
            last = min(i + overlay.hold, len(script.shots)) - 1
            end = starts[last] + script.shots[last].seconds
            same = [n for n, c in enumerate(cards) if c.kind == overlay.kind]
            if same and cards[same[-1]].text == overlay.text and cards[same[-1]].end >= starts[i]:
                cards[same[-1]] = replace(cards[same[-1]], end=max(end, cards[same[-1]].end))
                continue
            cards.append(Card(overlay.kind, overlay.text, starts[i], end))
    following: dict[str, float] = {}
    for n in reversed(range(len(cards))):
        card = cards[n]
        cards[n] = replace(card, end=min(card.end, following.get(card.kind, card.end)))
        following[card.kind] = card.start
    return cards


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
