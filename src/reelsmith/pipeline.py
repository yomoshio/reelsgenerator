"""The stages of the conveyor in order, and the services they need.

Every stage talks to one GPU service, so the conveyor can hold the card for it. That is
why the judge has stages of its own, `pick` and `check`, between the ComfyUI ones."""

import asyncio
import hashlib
import itertools
import re
import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol
from uuid import UUID

from reelsmith.checks import (
    bare,
    misspoken,
    present,
    problems,
    spoken_words,
    told_length,
    unsaid_plates,
)
from reelsmith.graphics import side_by_side
from reelsmith.models import (
    SHOT_PADDING,
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
    shot_seconds,
)
from reelsmith.pricing import Tariff, metered
from reelsmith.services.ffmpeg import Caption, Card, Cut, Segment, Word, captions, shift, to_ass
from reelsmith.styles import Style, Styles

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
    voice_tries: int = 3
    passage_words: int = 40


class Llm(Protocol):
    name: str

    async def plan(self, idea: str, style: Style, notes: str | None = None) -> Outline: ...

    async def write(self, idea: str, style: Style, notes: str | None = None) -> Script: ...

    async def review(self, script: Script, style: Style, outline: str = "") -> Verdict: ...

    async def pick(
        self, brief: str, images: list[Path], style: Style, reference: Path | None = None
    ) -> int: ...

    async def inspect(self, motion: str, stills: list[Path], style: Style) -> Verdict: ...

    async def judge(self, script: Script, stills: list[Path], style: Style) -> Verdict: ...

    def widest(self, count: int) -> int:
        """The widest still of which `count` fit in one request."""
        ...


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

    async def speak(self, text: str, out: Path, voice: str | None = None) -> Path: ...


class Composer(Protocol):
    name: str
    suffix: str

    async def compose(self, brief: str, *, seconds: float, seed: int, out: Path) -> Path: ...


class Transcriber(Protocol):
    async def words(self, audio: Path) -> list[Word]: ...


class Montage(Protocol):
    async def seconds(self, media: Path) -> float: ...

    async def cut(self, audio: Path, start: float, end: float, out: Path) -> Path: ...

    async def stills(self, video: Path, count: int, out_dir: Path) -> list[Path]: ...

    async def frame_at(self, video: Path, at: float, out: Path) -> Path: ...

    async def stills_at(
        self, video: Path, times: list[float], out_dir: Path, *, widest: int
    ) -> list[Path]: ...

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
    language: str | None = None  # scripts in another language go back to the writer

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

    def passage(self, first: int, suffix: str = ".wav") -> Path:
        return self._file(f"voice/passage-{first:02d}{suffix}")

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
    """The idea, a sentence or a whole story, first becomes an outline with the whole
    voiceover told as one story; an outline whose voiceover would run outside the
    channel's length is planned again. The writer then only cuts that voiceover into shots
    and draws them, so the story keeps one voice from start to end. Writer and critic go
    round until the script passes or the rewrites are spent. A script with a problem
    `checks` can see cannot pass. The best draft is kept either way."""
    style = s.styles.get(job.recipe.style)
    if job.outline is None:
        planned: str | None = None
        for _ in range(s.gates.rewrites + 1):
            with metered(job, s.tariff, stage="plan", provider=s.llm.name):
                job.outline = await s.llm.plan(job.idea, style, planned)
            if not (planned := told_length(job.outline.narration, style)):
                break
    assert job.outline is not None
    brief = job.outline.as_brief()
    best: tuple[Script, Verdict] | None = None
    notes: str | None = None
    for _ in range(s.gates.rewrites + 1):
        with metered(job, s.tariff, stage="script", provider=s.llm.name):
            script = await s.llm.write(brief, style, notes)
        with metered(job, s.tariff, stage="critic", provider=s.llm.name):
            verdict = await s.llm.review(script, style, brief)
        if found := problems(script, style, s.language, job.outline.narration):
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
    """Before pictures on purpose: the spoken lines decide how long their shots last. The
    narrator reads several shots in one take, so the voice runs on across the cuts instead
    of starting afresh on every line, and each take is heard back: a take with words the
    lines do not have is spoken again. The take is then cut into the shots' lines where the
    transcript says they meet, and only the last shot of a take gets a breath after it."""
    script, files = job.require_script(), Files(s.media, job.id)
    narrator = s.styles.get(job.recipe.style).voice
    for passage in passages([shot.line for shot in script.shots], s.gates.passage_words):
        lines = [script.shots[i].line for i in passage]
        text = " ".join(lines)
        for take in range(1, s.gates.voice_tries + 1):
            with metered(
                job, s.tariff, stage="voice", provider=s.narrator.name, units=len(text),
                shot=passage[0],
            ):  # fmt: skip
                out = files.passage(passage[0], s.narrator.suffix)
                audio = await s.narrator.speak(text, out, voice=narrator)
            heard = await s.transcriber.words(audio)
            if not (extra := misspoken(text, " ".join(w.text for w in heard))):
                break
            if take == s.gates.voice_tries:
                where = ", ".join(str(i + 1) for i in passage)
                raise StageError(f"shots {where}: the narrator adds «{extra}» to the lines")
        length = await s.montage.seconds(audio)
        for i, (start, end) in zip(passage, split(lines, heard, length), strict=True):
            piece = await s.montage.cut(audio, start, end, files.voice(i, s.narrator.suffix))
            breath = SHOT_PADDING if i == passage[-1] else 0.0
            script.shots[i].seconds = shot_seconds(end - start, padding=breath)
            job.assets.voices[i] = files.relative(piece)


def passages(lines: list[str], most: int) -> list[list[int]]:
    """Neighbouring lines read in one take, at most `most` words each; a longer line is a
    take of its own, and 0 reads every line alone."""
    taken: list[list[int]] = []
    words = 0
    for i, line in enumerate(lines):
        count = len(line.split())
        if taken and most and words + count <= most:
            taken[-1].append(i)
            words += count
        else:
            taken.append([i])
            words = count
    return taken


def split(lines: list[str], heard: list[Word], length: float) -> list[tuple[float, float]]:
    """Where each line starts and ends in one recording of them all: halfway through the
    pause between one line's last heard word and the next line's first. A line the
    transcript lost runs from where the line before it ended to where the next one starts;
    where neither is known, the lines share the time by the length of their text."""
    owner = [i for i, line in enumerate(lines) for _ in spoken_words(line)]
    tokens = [(t, w) for w in heard for t in spoken_words(w.text)]
    matcher = SequenceMatcher(
        a=[t for line in lines for t in spoken_words(line)],
        b=[t for t, _ in tokens],
        autojunk=False,
    )
    first: dict[int, float] = {}
    last: dict[int, float] = {}
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            word = tokens[b + k][1]
            first.setdefault(owner[a + k], word.start)
            last[owner[a + k]] = word.end
    known = {0: 0.0, len(lines): length}
    for i in range(1, len(lines)):
        end, start = last.get(i - 1), first.get(i)
        if end is not None and start is not None:
            if end <= start:
                known[i] = (end + start) / 2
        elif (edge := end if end is not None else start) is not None:
            known[i] = edge
    edges = [0]
    for i in sorted(known)[1:]:
        if known[i] >= known[edges[-1]] or i == len(lines):
            edges.append(i)
    cuts = [0.0] * (len(lines) + 1)
    for left, right in itertools.pairwise(edges):
        weights = [len(line) or 1 for line in lines[left:right]]
        done = 0
        for k in range(left, right):
            cuts[k] = known[left] + (known[right] - known[left]) * done / sum(weights)
            done += weights[k - left]
    cuts[-1] = length
    return [(cuts[i], max(cuts[i], cuts[i + 1])) for i in range(len(lines))]


async def paint(job: Job, s: Services) -> None:
    """Candidate frames for every shot; `pick` chooses among them in the next stage. With a
    `cast_image` model every character first gets a portrait in each outfit the story puts
    them in, and a shot with people is drawn from the portraits of up to three of them side
    by side, so faces, hair, clothes and the drawing hold from shot to shot."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    painter = s.painter(job.recipe.image)
    portraits = await _portraits(job, s, style) if job.recipe.cast_image else {}
    for i, shot in enumerate(script.shots):
        if i in job.assets.candidates or script.continued(i):
            continue
        cast = present(shot, script)
        where = script.setting(shot)
        prompt = ". ".join(
            p
            for p in (where, script.looks_of(cast, shot.wears), shot.picture, style.look.frame)
            if p
        )
        artist, reference = painter, None
        if job.recipe.cast_image and (drawn := _drawn(shot, cast, portraits)):
            artist = s.painter(job.recipe.cast_image)
            reference = await _reference(files, drawn, portraits)
            place = f" The place: {where}." if where else ""
            prompt = f"{_who(script, shot, drawn)}{place} {shot.picture}. {style.look.frame}"
        made: list[Path] = []
        for k in range(s.gates.candidates):
            seed = seed_for(job.id, 1000 + i * 10 + k)
            with metered(job, s.tariff, stage="frame", provider=artist.name, shot=i):
                out = files.frame(i, k)
                made.append(await artist.paint(prompt, seed=seed, out=out, reference=reference))
        job.assets.candidates[i] = [files.relative(p) for p in made]


def dressed_key(name: str, outfit: str | None) -> str:
    """How `assets.cast` names a character's portrait in one outfit."""
    return f"{name}|{outfit}" if outfit else name


def _drawn(shot: Shot, cast: list[str], portraits: Mapping[str, str]) -> list[str]:
    """The keys of the portraits a shot is drawn from: its first three people that have one."""
    keys = [dressed_key(name, shot.wears.get(name)) for name in cast]
    return [key for key in keys if key in portraits][:3]


async def _reference(files: Files, keys: list[str], portraits: Mapping[str, str]) -> Path:
    paths = [files.resolve(portraits[key]) for key in keys]
    if len(paths) == 1:
        return paths[0]
    name = hashlib.sha1("|".join(map(str, paths)).encode()).hexdigest()[:12]
    return await asyncio.to_thread(side_by_side, paths, files.base / "cast" / f"{name}.png")


def _who(script: Script, shot: Shot, keys: list[str]) -> str:
    """What the reference image shows, for a prompt that asks for the same people."""
    people = [key.split("|")[0] for key in keys]
    looks = [f"{n}, {script.character(n).dressed(shot.wears.get(n))}" for n in people]
    if len(looks) == 1:
        shown, same = f"The reference image shows {looks[0]}.", "the same person"
    else:
        shown = f"The reference image shows, from left to right: {'; '.join(looks)}."
        same = "the same people"
    return (
        f"{shown} Draw {same} with exactly the same faces, hair and clothes, in the same "
        "drawing style, in a new picture:"
    )


async def _portraits(job: Job, s: Services, style: Style) -> dict[str, str]:
    """One full-figure portrait per character and outfit. The file is named after the look,
    the outfit and the style, so the same character described the same way gets the same
    portrait in every episode of a serial, and is painted only once."""
    script, files = job.require_script(), Files(s.media, job.id)
    painter = s.painter(job.recipe.image)
    worn = {(name, outfit) for shot in script.shots for name, outfit in shot.wears.items()}
    for character in script.characters:
        for outfit in (None, *sorted(o for n, o in worn if n == character.name)):
            if outfit is not None and outfit not in character.outfits:
                continue
            key = dressed_key(character.name, outfit)
            if key in job.assets.cast:
                continue
            look = character.dressed(outfit)
            digest = hashlib.sha1(f"{style.name}|{look}".encode()).hexdigest()[:12]
            portrait = s.media / "cast" / f"{digest}.png"
            if not portrait.exists():
                portrait.parent.mkdir(parents=True, exist_ok=True)
                prompt = (
                    f"{look}. Full figure from head to feet, standing, facing the viewer, "
                    f"plain background, character reference. {style.look.frame}"
                )
                with metered(job, s.tariff, stage="cast", provider=painter.name):
                    await painter.paint(prompt, seed=int(digest, 16) % 2**31, out=portrait)
            job.assets.cast[key] = files.relative(portrait)
    return job.assets.cast


async def pick(job: Job, s: Services) -> None:
    """The judge picks one candidate per shot. A shot drawn from portraits shows the judge
    those portraits too, and a candidate that changes a person or the drawing loses."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    for i, shot in enumerate(script.shots):
        if i in job.assets.frames or script.continued(i):
            continue
        images = [files.resolve(p) for p in job.assets.candidates[i]]
        drawn = (
            _drawn(shot, present(shot, script), job.assets.cast) if job.recipe.cast_image else []
        )
        reference = await _reference(files, drawn, job.assets.cast) if drawn else None
        with metered(job, s.tariff, stage="pick", provider=s.llm.name, shot=i):
            chosen = await s.llm.pick(shot.picture, images, style, reference=reference)
        job.assets.frames[i] = job.assets.candidates[i][chosen]


async def animate(job: Job, s: Services) -> None:
    """One clip per shot from its chosen frame. A shot that continues the one before starts
    from the frame that shot's clip ends on, so the two play as one take. Shots that already
    have a clip are skipped, so a rewind redoes only what `check` or QA threw away; the seed
    moves with the attempt."""
    script, files = job.require_script(), Files(s.media, job.id)
    style = s.styles.get(job.recipe.style)
    for i, shot in enumerate(script.shots):
        if i in job.assets.clips:
            continue
        if script.continued(i):
            before = files.resolve(job.assets.clips[i - 1])
            start = await s.montage.frame_at(before, script.shots[i - 1].seconds, files.frame(i))
            job.assets.frames[i] = files.relative(start)
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
        for j in script.take(i):
            job.assets.clips.pop(j, None)
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
    stills = await s.montage.stills_at(
        final, middles, files.stills(None), widest=s.llm.widest(len(middles))
    )
    with metered(job, s.tariff, stage="qa", provider=s.llm.name):
        verdict = await s.llm.judge(script, stills, style)
    verdict.bad_shots = [i for i in verdict.bad_shots if 0 <= i < len(script.shots)]
    job.qa = verdict
    if verdict.score < s.gates.qa_pass:
        for i in verdict.bad_shots or list(job.assets.clips):
            for j in script.take(i):
                job.assets.clips.pop(j, None)
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
