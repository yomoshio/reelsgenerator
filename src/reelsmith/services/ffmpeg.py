"""Cut planning, subtitles and the ffmpeg calls that render them.

The planning functions are pure: they build argument lists and ASS text. `FfmpegMontage`
only runs what they build."""

import asyncio
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from reelsmith.models import StageError
from reelsmith.styles import Plate, Style

WIDTH, HEIGHT, FPS = 1080, 1920, 30
# Clips are rendered at 480x848, so stills wider than this only add tokens for the judge.
STILL_WIDTH = 540
MUSIC_LEVEL = 0.22
# A narrator who sounds close and present: rumble cut, peaks evened out, a little lift.
VOICE_CHAIN = "highpass=f=70,acompressor=threshold=0.125:ratio=3:attack=5:release=120:makeup=2"
# The level short-video platforms normalise to, so a video is neither quiet nor clipped.
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    accent: bool = False


@dataclass(frozen=True, slots=True)
class Caption:
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


@dataclass(frozen=True, slots=True)
class Card:
    """An overlay placed on the timeline of the whole video."""

    kind: str
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Segment:
    clip: Path
    voice: Path
    seconds: float


@dataclass(frozen=True, slots=True)
class Cut:
    segments: tuple[Segment, ...]
    music: Path
    subtitles: Path


def ffmpeg_args(cut: Cut, out: Path, *, music_level: float = MUSIC_LEVEL) -> list[str]:
    inputs: list[str] = []
    for seg in cut.segments:
        inputs += ["-i", str(seg.clip), "-i", str(seg.voice)]
    inputs += ["-stream_loop", "-1", "-i", str(cut.music)]
    music_index = 2 * len(cut.segments)

    graph = [*_video_chains(cut.segments), *_voice_chains(cut.segments)]
    n = len(cut.segments)
    video_labels = "".join(f"[v{i}]" for i in range(n))
    voice_labels = "".join(f"[a{i}]" for i in range(n))
    graph += [
        f"{video_labels}concat=n={n}:v=1:a=0,subtitles=filename='{_quoted(cut.subtitles)}'[video]",
        f"{voice_labels}concat=n={n}:v=0:a=1,{VOICE_CHAIN},asplit=2[voice][key]",
        f"[{music_index}:a]aresample=48000,volume={music_level}[bed]",
        "[bed][key]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[ducked]",
        f"[voice][ducked]amix=inputs=2:duration=first:normalize=0,{LOUDNESS}[audio]",
    ]
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(graph),
        "-map", "[video]", "-map", "[audio]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]  # fmt: skip


def stills_args(
    video: Path, count: int, seconds: float, out_dir: Path, *, width: int = STILL_WIDTH
) -> list[str]:
    spacing = max(seconds / count, 0.001)
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-vf", f"fps=1/{spacing:.3f},scale={width}:-2", "-frames:v", str(count),
        str(out_dir / "%02d.png"),
    ]  # fmt: skip


def _video_chains(segments: Iterable[Segment]) -> Iterator[str]:
    for i, seg in enumerate(segments):
        yield (
            f"[{2 * i}:v]tpad=stop_mode=clone:stop_duration={seg.seconds:.3f},"
            f"trim=duration={seg.seconds:.3f},setpts=PTS-STARTPTS,"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1[v{i}]"
        )


def _voice_chains(segments: Iterable[Segment]) -> Iterator[str]:
    for i, seg in enumerate(segments):
        d = f"{seg.seconds:.3f}"
        yield f"[{2 * i + 1}:a]aresample=48000,apad=whole_dur={d},atrim=duration={d}[a{i}]"


def _quoted(path: Path) -> str:
    # Inside a quoted filter argument nothing can be escaped, so refuse what would break it.
    text = str(path)
    if "'" in text:
        raise ValueError(f"subtitle path cannot contain a quote: {text}")
    return text


def shift(words: Iterable[Word], offset: float) -> list[Word]:
    return [Word(w.text, w.start + offset, w.end + offset, w.accent) for w in words]


def captions(words: Iterable[Word], *, max_words: int = 3, max_gap: float = 0.6) -> list[Caption]:
    """Groups words into short on-screen captions the way shorts are usually subtitled."""
    groups: list[list[Word]] = []
    for word in words:
        current = groups[-1] if groups else None
        if current and len(current) < max_words and word.start - current[-1].end <= max_gap:
            current.append(word)
        else:
            groups.append([word])
    return [Caption(tuple(g)) for g in groups]


def to_ass(lines: Iterable[Caption], style: Style, cards: Iterable[Card] = ()) -> str:
    look = style.captions
    plates = style.overlays
    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {WIDTH}",
        f"PlayResY: {HEIGHT}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        f"Style: Caption,{look.font},{look.size},{_colour(look.spoken)},{_colour(look.upcoming)},"
        f"{_colour(look.outline)},&H64000000,-1,1,{look.outline_px},0,2,80,80,{look.margin_v}",
        *(_plate_style(kind, plate, look.font) for kind, plate in plates.items()),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]
    for card in cards:
        if card.kind in plates:
            out.append(
                _event(
                    1,
                    card.start,
                    card.end,
                    f"Plate-{card.kind}",
                    _card_text(card, plates[card.kind]),
                )
            )
    out += [_event(0, c.start, c.end, "Caption", _caption_text(c, style)) for c in lines]
    return "\n".join(out) + "\n"


def _plate_style(kind: str, plate: Plate, default_font: str) -> str:
    # In a boxed style the outline colour paints the box and the outline width is its padding.
    return (
        f"Style: Plate-{kind},{plate.font or default_font},{plate.size},{_colour(plate.ink)},"
        f"{_colour(plate.ink)},{_colour(plate.fill)},&H00000000,-1,3,{plate.pad},0,{plate.align},"
        f"{plate.margin_l},{plate.margin_r},{plate.margin_v}"
    )


def _caption_text(caption: Caption, style: Style) -> str:
    look = style.captions
    parts: list[str] = []
    for i, word in enumerate(caption.words):
        following = caption.words[i + 1].start if i + 1 < len(caption.words) else caption.end
        sweep = f"\\k{max(round((following - word.start) * 100), 1)}" if look.karaoke else ""
        colour = _tag(look.accent if word.accent else look.spoken)
        parts.append(f"{{\\1c{colour}{sweep}}}{_plain(word.text).upper()}")
    return " ".join(parts)


_NUMBERED = re.compile(r"^(\d+\.)\s*(.*)$")
_POP = "{\\fad(140,100)\\fscx85\\fscy85\\t(0,180,\\fscx100\\fscy100)}"


def _card_text(card: Card, plate: Plate) -> str:
    first, _, second = card.text.partition("|")
    head = _plain(first).strip()
    head = head.upper() if plate.upper else head
    if plate.number and (numbered := _NUMBERED.match(head)):
        numeral, rest = numbered[1], numbered[2]
        head = f"{{\\1c{_tag(plate.number)}}}{numeral}{{\\1c{_tag(plate.ink)}}} {rest}"
    if detail := _plain(second).strip():
        detail = detail.upper() if plate.upper else detail
        head += f"\\N{{\\fs{round(plate.size * 0.6)}\\b0}}{detail}"
    return _POP + head


def _event(layer: int, start: float, end: float, style: str, text: str) -> str:
    return f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},{text}"


def _plain(text: str) -> str:
    return re.sub(r"[{}\\]", "", text)


def _colour(hex_rgb: str) -> str:
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H00{b}{g}{r}".upper()


def _tag(hex_rgb: str) -> str:
    return _colour(hex_rgb) + "&"


def _ass_time(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


class StillAnimator:
    """A slow camera move over the still frame, made by ffmpeg on the CPU. Nothing can
    melt or drift, and a clip takes seconds; the price is that nothing in the frame moves."""

    name = "still"

    def __init__(self, *, max_seconds: float = 8.0) -> None:
        self.max_seconds = max_seconds

    def length(self, seconds: float) -> float:
        return seconds

    async def animate(
        self, frame: Path, motion: str, *, seconds: float, seed: int, out: Path
    ) -> Path:
        await run(*still_args(frame, seconds, seed, out))
        return out


def still_args(frame: Path, seconds: float, seed: int, out: Path) -> list[str]:
    """Push in, pull out or drift sideways, picked by the seed so neighbouring shots differ."""
    frames = max(round(seconds * FPS), 1)
    step = 0.08 / frames
    moves = (
        (f"1+{step:.6f}*on", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        (f"1.08-{step:.6f}*on", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        ("1.08", f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"),
    )
    zoom, x, y = moves[seed % len(moves)]
    # zoompan jitters on a frame its own size; working on a doubled frame keeps the move smooth.
    graph = (
        f"scale={2 * WIDTH}:{2 * HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={2 * WIDTH}:{2 * HEIGHT},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(frame), "-vf", graph, "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out),
    ]  # fmt: skip


async def preview(style: Style, out: Path) -> Path:
    """One frame with sample captions and every overlay of the style, for tuning a template."""
    words = [
        Word("Это", 0.2, 0.6),
        Word("ударное", 0.7, 1.3, accent=True),
        Word("слово.", 1.4, 2.0),
    ]
    cards = [
        Card(kind, f"1. {kind}" if plate.number else f"{kind} | пример", 0.0, 3.0)
        for kind, plate in style.overlays.items()
    ]
    subtitles = out.with_suffix(".ass")
    subtitles.write_text(to_ass(captions(words), style, cards), encoding="utf-8")
    await run(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=0x0b1020:s={WIDTH}x{HEIGHT}:d=3:r=10,format=yuv420p",
        "-vf", f"subtitles=filename='{_quoted(subtitles)}'",
        "-ss", "1.2", "-frames:v", "1", str(out),
    )  # fmt: skip
    return out


class FfmpegMontage:
    def __init__(self, *, music_level: float = MUSIC_LEVEL, still_width: int = STILL_WIDTH) -> None:
        self.music_level = music_level
        self.still_width = still_width

    async def seconds(self, media: Path) -> float:
        out = await run(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(media),
        )  # fmt: skip
        return float(out)

    async def stills(self, video: Path, count: int, out_dir: Path) -> list[Path]:
        seconds = await self.seconds(video)
        await run(*stills_args(video, count, seconds, out_dir, width=self.still_width))
        return await asyncio.to_thread(lambda: sorted(out_dir.glob("*.png")))

    async def stills_at(self, video: Path, times: list[float], out_dir: Path) -> list[Path]:
        made: list[Path] = []
        for n, at in enumerate(times):
            out = out_dir / f"{n:02d}.png"
            await run(
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{at:.3f}", "-i", str(video),
                "-frames:v", "1", "-vf", f"scale={self.still_width}:-2", str(out),
            )  # fmt: skip
            made.append(out)
        return made

    async def render(self, cut: Cut, out: Path) -> Path:
        await run(*ffmpeg_args(cut, out, music_level=self.music_level))
        return out


async def run(*argv: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = stderr.decode(errors="replace").strip().splitlines()[-5:]
        raise StageError(f"{argv[0]} exited {proc.returncode}: {' | '.join(tail)}")
    return stdout.decode().strip()
