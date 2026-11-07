"""Stand-ins for every model, with no weights and no network.

Every decision is a function of the inputs, so a rerun reproduces the run. The media is
real: colour clips and tones made with ffmpeg, so the assembly runs on real files."""

import hashlib
import json
import random
import re
from pathlib import Path

from reelsmith.models import (
    Adaptation,
    Character,
    EpisodeIdea,
    Metrics,
    Outline,
    Overlay,
    Part,
    Script,
    Season,
    Shot,
    Verdict,
)
from reelsmith.services.ffmpeg import FfmpegMontage, Word, run
from reelsmith.styles import Style

HOOK_KINDS = ("question", "threat", "promise", "secret", "countdown")
RETENTION = {"question": 0.55, "threat": 0.5, "promise": 0.45, "secret": 0.6, "countdown": 0.4}
SECONDS_PER_CHAR = 0.065

LINES = (
    "Никто не выходит отсюда после полуночи.",
    "Она слышала шаги, но коридор был пуст.",
    "Дверь в третью палату всегда закрыта изнутри.",
    "Свет мигнул, и на стене появилась вторая тень.",
    "Он понял, что часы идут назад.",
    "Утром в журнале появилась запись её почерком.",
)
PICTURES = (
    "empty hospital corridor at night, one flickering ceiling light",
    "a nurse at the end of the corridor looking over her shoulder",
    "a closed door with a small wired window, light behind it",
    "a wall with two shadows, one of them not matching anyone",
    "a round wall clock, hands blurred",
    "an open logbook on a desk, pen still wet",
)
MOTIONS = (
    "slow push in, light flickers twice",
    "handheld, she turns slowly toward camera",
    "static, the light behind the window dims",
    "slow pan left, the second shadow stays still",
    "clock hands run backwards, slight zoom",
    "tilt down onto the page, ink spreads",
)


def rng(*parts: object) -> random.Random:
    digest = hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _fingerprint(files: list[Path]) -> str:
    return hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest()


def _colour(r: random.Random) -> str:
    return f"0x{r.randrange(256):02x}{r.randrange(256):02x}{r.randrange(256):02x}"


class SyntheticLlm:
    """`flag` is how often a clip is flagged, `reject` how often a cut is turned down."""

    name = "ollama"

    def __init__(self, *, flag: float = 0.0, reject: float = 0.0) -> None:
        self.flag = flag
        self.reject = reject

    async def season(self, synopsis: str, style: Style, episodes: int) -> Season:
        return Season(
            title=" ".join(synopsis.split()[:3]),
            world=synopsis,
            characters=[Character(name="Vera", look="nurse, 30s, tired eyes, grey cardigan")],
            episodes=[
                EpisodeIdea(title=f"Night {n}", logline=LINES[n % len(LINES)])
                for n in range(1, episodes + 1)
            ],
        )

    async def retell(self, passage: str) -> list[str]:
        """Each sentence of the passage is an event."""
        return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(passage.split())) if s]

    async def adapt(self, events: list[str], style: Style, most: int) -> Adaptation:
        """Two episodes split in the middle when the story is long enough, one otherwise."""
        count = 2 if most > 1 and len(events) > 1 else 1
        ends = [len(events) * (n + 1) // count for n in range(count)]
        return Adaptation(
            title=" ".join(events[0].split()[:3]),
            world=events[0],
            characters=[Character(name="Vera", look="nurse, 30s, tired eyes, grey cardigan")],
            parts=[
                Part(title=f"Part {n}", logline=events[end - 1], last=end)
                for n, end in enumerate(ends, 1)
            ],
        )

    async def plan(self, idea: str, style: Style) -> Outline:
        return Outline(
            title=idea.split(".", maxsplit=1)[0][:60],
            characters=[Character(name="Vera", look="nurse, 30s, tired eyes, grey cardigan")],
            beats=list(LINES),
            planted="the logbook on the desk",
            ending=LINES[-1],
        )

    async def write(self, idea: str, style: Style, notes: str | None = None) -> Script:
        order = list(range(len(LINES)))
        rng(idea, notes or "").shuffle(order)
        order = [order[n % len(order)] for n in range(max(len(order), style.story.shots[0]))]
        shots = [
            Shot(
                line=LINES[i],
                picture=PICTURES[i],
                motion=MOTIONS[i],
                cast=["Vera"],
                stress=[LINES[i].split()[0].strip(".,")],
            )
            for i in order
        ]
        for kind, number in zip(style.overlays, range(1, len(shots), 3), strict=False):
            shots[number].overlays.append(Overlay(kind=kind, text=f"{number}. {kind}", hold=2))
        return Script(
            title=idea.split(".", maxsplit=1)[0][:60],
            hook=shots[0].line,
            hook_kind=HOOK_KINDS[rng(idea).randrange(len(HOOK_KINDS))],
            characters=[Character(name="Vera", look="nurse, 30s, tired eyes, grey cardigan")],
            shots=shots,
            music="slow drone, sparse piano, unsettling",
        )

    async def review(self, script: Script, style: Style, outline: str = "") -> Verdict:
        score = round(5 + 4.9 * rng(script.model_dump_json()).random(), 1)
        return Verdict(score=score, notes="tighten the hook, cut the last line")

    async def pick(self, brief: str, images: list[Path], style: Style) -> int:
        return rng(brief, *images).randrange(len(images))

    async def inspect(self, motion: str, stills: list[Path], style: Style) -> Verdict:
        if rng(motion, _fingerprint(stills)).random() < self.flag:
            return Verdict(score=4.0, notes="motion smear on the subject")
        return Verdict(score=8.0)

    async def judge(self, script: Script, stills: list[Path], style: Style) -> Verdict:
        r = rng(script.title, _fingerprint(stills))
        if r.random() < self.reject:
            shot = r.randrange(len(script.shots))
            return Verdict(score=5.0, notes=f"shot {shot} drifts off model", bad_shots=[shot])
        return Verdict(score=8.5)


class SyntheticPainter:
    def __init__(self, name: str = "z-image") -> None:
        self.name = name

    async def paint(
        self, prompt: str, *, seed: int, out: Path, reference: Path | None = None
    ) -> Path:
        colour = _colour(rng(prompt, seed, reference or ""))
        await run(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={colour}:s=720x1280", "-frames:v", "1", str(out),
        )  # fmt: skip
        return out


class SyntheticAnimator:
    def __init__(self, name: str = "wan-2.2", max_seconds: float = 5.0) -> None:
        self.name = name
        self.max_seconds = max_seconds

    def length(self, seconds: float) -> float:
        return seconds

    async def animate(
        self, frame: Path, motion: str, *, seconds: float, seed: int, out: Path
    ) -> Path:
        colour = _colour(rng(self.name, motion, seed))
        await run(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={colour}:s=360x640:d={seconds:.3f}:r=12",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out),
        )  # fmt: skip
        return out


class SyntheticNarrator:
    name = "voxcpm"
    suffix = ".wav"

    async def speak(self, text: str, out: Path, delivery: str = "") -> Path:
        seconds = max(1.0, SECONDS_PER_CHAR * len(text))
        await _tone(out, frequency=220, seconds=seconds)
        out.with_suffix(".txt").write_text(text, encoding="utf-8")
        return out


class SyntheticComposer:
    name = "ace-step"
    suffix = ".flac"

    async def compose(self, brief: str, *, seconds: float, seed: int, out: Path) -> Path:
        await _tone(out, frequency=55, seconds=seconds)
        return out


async def _tone(out: Path, *, frequency: int, seconds: float) -> None:
    await run(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds:.3f}",
        "-ac", "1", "-ar", "24000", str(out),
    )  # fmt: skip


class SyntheticTranscriber:
    """Word timings from the narrator's sidecar text, spread evenly over the recording."""

    def __init__(self, montage: FfmpegMontage) -> None:
        self._montage = montage

    async def words(self, audio: Path) -> list[Word]:
        words = audio.with_suffix(".txt").read_text(encoding="utf-8").split()
        step = await self._montage.seconds(audio) / len(words)
        return [Word(w, i * step, (i + 1) * step) for i, w in enumerate(words)]


class SyntheticAnalytics:
    async def measure(self, posted: str) -> Metrics:
        meta = json.loads((Path(posted) / "post.json").read_text(encoding="utf-8"))
        r = rng(posted)
        retention = RETENTION.get(meta["hook_kind"], 0.5) + r.uniform(-0.1, 0.1)
        retention = min(max(retention, 0.0), 1.0)
        return Metrics(
            views=r.randint(1000, 20000), retention_3s=retention, completion=retention * 0.6
        )
