"""A beat rendered by code: the scene and the hero, the graphics coming up on the narrator's
words, burnt-in captions, the voice over a bed that never goes silent, and a short sound on
every reveal.

Frames are composed with Pillow and piped to ffmpeg as raw video. A frame where nothing
moves is the previous frame again, so a beat renders in seconds on a CPU. Without a voice
the words are timed from their syllables, which is enough to look at the frames."""

import asyncio
import re
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

from reelsmith.beats import PACE, Beat, BeatScript, Library, syllables, word_at, words
from reelsmith.checks import bare
from reelsmith.graphics import H, Sprite, W, compose, hero, reveal_sprites, scene, state
from reelsmith.models import StageError
from reelsmith.services.ffmpeg import FPS, VOICE_CHAIN, Word, captions, to_ass
from reelsmith.styles import Style

LEAD = 0.15  # silence before the first word when the words are timed from syllables
TAIL = 0.35  # the beat holds this long after its last word, room for the transition
PAUSES = {".": 0.3, "!": 0.3, "?": 0.3, "…": 0.35, ",": 0.12, ";": 0.15, ":": 0.15, "—": 0.15}
SFX_LEVEL = 0.4  # about 8 dB under the voice
BED_LEVEL = 0.35
BED_FLOOR = 0.25  # the bed is never ducked deeper than 12 dB
# The middle of the reference's band, -16 to -14 LUFS: one pass over a short beat lands a
# few tenths above its target.
LOUDNESS = "loudnorm=I=-15:TP=-1.5:LRA=11"
_SHOWN = re.compile(r"\S+")


@dataclass(frozen=True)
class Timing:
    """When each word of a beat is said. `shown` are the words as captions print them,
    punctuation attached; `said` are the words as `beats.words` counts them."""

    shown: list[Word]
    said: list[tuple[float, float]]

    @property
    def end(self) -> float:
        return self.said[-1][1] if self.said else 0.0


def timing(beat: Beat, heard: Sequence[Word] = ()) -> Timing:
    """From the transcript of the beat's voice where there is one: words it heard
    differently share the time of what it heard in their place. Otherwise from syllables
    at the narrator's pace, with a pause after punctuation."""
    tokens = _tokens(beat.text)
    parts = [words(t) for t in tokens]
    flat = [p for ps in parts for p in ps]
    said = _heard(flat, heard) if heard else _paced(tokens, parts)
    shown, i = [], 0
    for token, ps in zip(tokens, parts, strict=True):
        start, end = said[i][0], said[i + len(ps) - 1][1]
        shown.append(Word(token, start, end))
        i += len(ps)
    return Timing(shown, said)


def _tokens(text: str) -> list[str]:
    """Words as printed, with a dash or any other mark standing alone glued to the word
    before it."""
    out: list[str] = []
    for token in _SHOWN.findall(text):
        if out and not words(token):
            out[-1] += " " + token
        else:
            out.append(token)
    return out


def _paced(tokens: list[str], parts: list[list[str]]) -> list[tuple[float, float]]:
    """Words one after another with a pause after punctuation, the whole stretched to the
    length the checks expect, so a preview runs as long as the beat will once voiced."""
    out: list[tuple[float, float]] = []
    t = 0.0
    for token, ps in zip(tokens, parts, strict=True):
        for p in ps:
            length = max(syllables(p), 1)
            out.append((t, t + length))
            t += length
        t += PACE * PAUSES.get(token.rstrip("»\"')")[-1:], 0.0)
    total = sum(max(syllables(p), 1) for ps in parts for p in ps) / PACE
    scale = total / out[-1][1] if out else 1.0
    return [(LEAD + a * scale, LEAD + b * scale) for a, b in out]


def _heard(flat: list[str], heard: Sequence[Word]) -> list[tuple[float, float]]:
    said = [bare(w.text) for w in heard]
    matcher = SequenceMatcher(a=flat, b=said, autojunk=False)
    out: list[tuple[float, float] | None] = [None] * len(flat)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "insert":
            continue
        if tag == "equal" or a2 - a1 == b2 - b1:
            for k in range(a2 - a1):
                out[a1 + k] = (heard[b1 + k].start, heard[b1 + k].end)
        elif b2 > b1:
            start, end = heard[b1].start, heard[b2 - 1].end
            step = (end - start) / (a2 - a1)
            for k in range(a2 - a1):
                out[a1 + k] = (start + k * step, start + (k + 1) * step)
    return _filled(out, heard[-1].end)


def _filled(found: list[tuple[float, float] | None], last: float) -> list[tuple[float, float]]:
    """Words nobody heard take the gap between their neighbours."""
    out: list[tuple[float, float]] = []
    for i, pair in enumerate(found):
        if pair is not None:
            out.append(pair)
            continue
        before = out[-1][1] if out else 0.0
        after = next((p[0] for p in found[i + 1 :] if p is not None), last)
        missing = next((k for k, p in enumerate(found[i:]) if p is not None), len(found) - i)
        step = max(after - before, 0.0) / (missing + 1)
        out.append((before, before + step))
    return out


def starts(beat: Beat, said: Timing) -> list[float]:
    """When each reveal comes up: the moment its word starts. A reveal whose word the beat
    never says comes up with the first word; the checks keep such scripts from rendering."""
    return [
        said.said[i][0] if (i := word_at(beat, r)) is not None else said.said[0][0]
        for r in beat.reveals
    ]


@dataclass
class Plan:
    """Everything a beat shows, on its own timeline: the backgrounds in turn, from the
    second they take over, and the sprites over them. `carried` go on to the next beat."""

    seconds: float
    backgrounds: list[tuple[float, Image.Image]]
    sprites: list[Sprite]
    carried: list[Sprite]


def plan(
    beat: Beat,
    library: Library,
    folder: Path | None,
    said: Timing,
    *,
    seconds: float,
    carried: Sequence[Sprite] = (),
) -> Plan:
    """The beat laid out. `carried` are graphics kept up from earlier beats, such as the
    rule card; a new rule card takes the place of the one carried. The plan's `carried` is
    what goes on to the next beat."""
    location = library.locations[beat.location]
    empty = scene(beat.location, location, folder)
    pose = beat.pose
    times = starts(beat, said)

    def with_hero(name: str) -> Image.Image:
        figure = hero(name, location.anchors, folder)
        img = empty.copy()
        img.alpha_composite(figure.image, (max(figure.xy[0], 0), max(figure.xy[1], 0)))
        return img

    backgrounds = [(0.0, with_hero(pose))]
    sprites = [Sprite(s.image, s.xy, 0.0, entrance="cut", kind=s.kind, keep=True) for s in carried]
    rows: dict[str, int] = {}
    stages: dict[str, int] = {}
    origin = location.anchors["hero"].x * W, location.anchors["hero"].y * H - 150
    for reveal, start in zip(beat.reveals, times, strict=True):
        if reveal.kind == "pose" and reveal.target in library.poses:
            backgrounds.append((start, with_hero(reveal.target)))
            continue
        stage = stages.get(reveal.target, 0) + 1 if reveal.kind == "prop_stage" else 0
        if reveal.kind == "prop_stage":
            stages[reveal.target] = stage
        prop = library.props.get(reveal.target)
        made = reveal_sprites(
            reveal,
            start=start,
            location=location,
            base=backgrounds[-1][1],
            rows=rows,
            stage=stage,
            stages=len(prop.stages) if prop else 0,
            origin=origin,
        )
        if reveal.kind == "rule_card":
            for s in sprites:
                if s.kind == "rule_card" and s.end > start:
                    s.end = start
        if reveal.kind == "diagram_step" and reveal.target in location.anchors:
            origin = location.anchors[reveal.target].x * W, location.anchors[reveal.target].y * H
        for s in made:
            s.kind, s.keep = reveal.kind, reveal.persist == "episode"
        sprites += made
    passed_on = [s for s in sprites if s.keep and s.end > seconds]
    return Plan(seconds, backgrounds, sprites, passed_on)


def frames(plan: Plan, fps: int = FPS) -> Iterator[bytes]:
    """Raw RGB frames of the beat. A frame that would look like the last one is not
    composed again."""
    last: tuple[object, ...] | None = None
    data = b""
    for n in range(round(plan.seconds * fps)):
        t = n / fps
        base = max(i for i, (start, _) in enumerate(plan.backgrounds) if start <= t)
        key = (base, *(state(s, t, fps) for s in plan.sprites))
        if key != last:
            data = compose(plan.backgrounds[base][1], plan.sprites, t).convert("RGB").tobytes()
            last = key
        yield data


def still(plan: Plan, t: float) -> Image.Image:
    base = max(i for i, (start, _) in enumerate(plan.backgrounds) if start <= t)
    return compose(plan.backgrounds[base][1], plan.sprites, t).convert("RGB")


def sheet(
    script: BeatScript, library: Library, folder: Path | None, width: int = 270
) -> Image.Image:
    """Every beat at its last frame, graphics carried from beat to beat as in the cut, in
    rows of six; words timed from syllables."""
    stills: list[Image.Image] = []
    carried: list[Sprite] = []
    for beat in script.beats:
        said = timing(beat)
        laid = plan(beat, library, folder, said, seconds=said.end + TAIL, carried=carried)
        carried = laid.carried
        stills.append(still(laid, laid.seconds - 1 / FPS).resize((width, width * H // W)))
    cols = min(len(stills), 6)
    rows = -(-len(stills) // cols)
    out = Image.new("RGB", (cols * width, rows * width * H // W))
    for n, img in enumerate(stills):
        out.paste(img, (n % cols * width, n // cols * width * H // W))
    return out


def accented(beat: Beat, said: Timing) -> list[Word]:
    """The captions' words, with the words that bring up a graphic stressed."""
    tokens = _tokens(beat.text)
    owner = [n for n, t in enumerate(tokens) for _ in words(t)]
    hit = {owner[i] for r in beat.reveals if (i := word_at(beat, r)) is not None}
    return [Word(w.text, w.start, w.end, n in hit) for n, w in enumerate(said.shown)]


def mix_args(
    voice: Path | None,
    sounds: Sequence[tuple[Path, float]],
    bed: Sequence[Path],
    seconds: float,
    out: Path,
) -> list[str]:
    """The beat's sound: the voice, the bed from the first frame to the last, ducked softly
    under the voice and never below its floor, and each sound on its reveal. 48 kHz stereo
    after the loudness pass, which works at 192 kHz inside."""
    d = f"{seconds:.3f}"
    inputs: list[str] = []
    graph: list[str] = []
    mixed: list[str] = []
    n = 0
    if voice is not None:
        inputs += ["-i", str(voice)]
        graph.append(
            f"[0:a]aresample=48000,aformat=channel_layouts=stereo,{VOICE_CHAIN},apad=whole_dur={d},atrim=duration={d},asplit=2[voice][key]"
        )
        mixed.append("[voice]")
        n = 1
    for path in bed:
        inputs += ["-stream_loop", "-1", "-i", str(path)]
    if bed:
        labels = "".join(f"[{n + k}:a]" for k in range(len(bed)))
        graph.append(
            f"{labels}amix=inputs={len(bed)}:normalize=0,aresample=48000,aformat=channel_layouts=stereo,atrim=duration={d},volume={BED_LEVEL},asplit=2[bed][floor]"
        )
        if voice is not None:
            graph.append(
                "[bed][key]sidechaincompress=threshold=0.05:ratio=3.5:attack=30:release=500[ducked]"
            )
            graph.append(f"[floor]volume={BED_FLOOR}[low]")
            mixed += ["[ducked]", "[low]"]
        else:
            graph.append("[floor]anullsink")
            mixed.append("[bed]")
        n += len(bed)
    for k, (path, at) in enumerate(sounds):
        inputs += ["-i", str(path)]
        ms = max(round(at * 1000), 0)
        graph.append(
            f"[{n + k}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"adelay={ms}|{ms},volume={SFX_LEVEL}[s{k}]"
        )
        mixed.append(f"[s{k}]")
    if not mixed:
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={d}"]
        mixed.append(f"[{n}:a]")
    graph.append(
        f"{''.join(mixed)}amix=inputs={len(mixed)}:duration=longest:normalize=0,"
        f"apad=whole_dur={d},atrim=duration={d},{LOUDNESS},aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo[audio]"
    )
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[audio]",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(out),
    ]


def encode_args(subtitles: Path, audio: Path, out: Path, fps: int = FPS) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(audio),
        "-vf",
        f"ass=filename='{subtitles}'",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]


def sounds_of(beat: Beat, times: Sequence[float], folder: Path) -> list[tuple[Path, float]]:
    """The library's sound for each reveal that has one, at the second it comes up."""
    out = []
    for key, at in zip(beat.sfx, times, strict=False):
        path = folder / "sfx" / f"{key}.wav"
        if path.exists():
            out.append((path, at))
    return out


def bed_of(beat: Beat, folder: Path) -> list[Path]:
    """The location's ambience and the series drone, those of them the series has."""
    found = [folder / "bed" / f"{beat.location}.wav", folder / "bed" / "drone.wav"]
    return [p for p in found if p.exists()]


async def render(
    beat: Beat,
    library: Library,
    folder: Path,
    style: Style,
    out: Path,
    *,
    voice: Path | None = None,
    heard: Sequence[Word] = (),
    voice_seconds: float = 0.0,
) -> Plan:
    """One beat to `out`: video with burnt-in captions and its sound. Gives the plan, so
    stills can be taken from it."""
    said = timing(beat, heard)
    seconds = max(voice_seconds, said.end + TAIL)
    laid = plan(beat, library, folder, said, seconds=seconds)
    work = out.with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    subtitles = work / "captions.ass"
    subtitles.write_text(
        to_ass(captions(accented(beat, said), max_words=style.captions.words), style),
        encoding="utf-8",
    )
    audio = work / "sound.wav"
    times = starts(beat, said)
    await asyncio.to_thread(
        subprocess.run,
        mix_args(voice, sounds_of(beat, times, folder), bed_of(beat, folder), seconds, audio),
        check=True,
    )
    await asyncio.to_thread(_encode, laid, encode_args(subtitles, audio, out))
    return laid


def _encode(laid: Plan, args: list[str]) -> None:
    with subprocess.Popen(args, stdin=subprocess.PIPE) as encoder:
        assert encoder.stdin is not None
        try:
            for frame in frames(laid):
                encoder.stdin.write(frame)
        finally:
            encoder.stdin.close()
    if encoder.returncode:
        raise StageError(f"ffmpeg exited with {encoder.returncode} while encoding the beat")
