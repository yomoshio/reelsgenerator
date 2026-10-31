"""Cut planning, subtitles and the ffmpeg calls that render them.

The planning functions are pure: they build argument lists and ASS text. `FfmpegMontage`
only runs what they build."""

import asyncio
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from reelsmith.models import StageError

WIDTH, HEIGHT, FPS = 1080, 1920, 30
MUSIC_LEVEL = 0.22


@dataclass(frozen=True, slots=True)
class Word:
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


def ffmpeg_args(cut: Cut, out: Path) -> list[str]:
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
        f"{voice_labels}concat=n={n}:v=0:a=1,asplit=2[voice][key]",
        f"[{music_index}:a]aresample=48000,volume={MUSIC_LEVEL}[bed]",
        "[bed][key]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[ducked]",
        "[voice][ducked]amix=inputs=2:duration=first:normalize=0[audio]",
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


def stills_args(video: Path, count: int, seconds: float, out_dir: Path) -> list[str]:
    spacing = max(seconds / count, 0.001)
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-vf", f"fps=1/{spacing:.3f}", "-frames:v", str(count),
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
    return [Word(w.text, w.start + offset, w.end + offset) for w in words]


def captions(words: Iterable[Word], *, max_words: int = 3, max_gap: float = 0.6) -> list[Word]:
    """Groups words into short on-screen captions the way shorts are usually subtitled."""
    groups: list[list[Word]] = []
    for word in words:
        current = groups[-1] if groups else None
        if current and len(current) < max_words and word.start - current[-1].end <= max_gap:
            current.append(word)
        else:
            groups.append([word])
    return [Word(" ".join(w.text for w in g), g[0].start, g[-1].end) for g in groups]


ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Caption, Montserrat ExtraBold, 92, &H00FFFFFF, &H00000000, &H64000000, -1, \
1, 6, 0, 2, 80, 80, 620

[Events]
Format: Layer, Start, End, Style, Text
"""


def to_ass(lines: Iterable[Word]) -> str:
    events = [
        f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Caption,{c.text.upper()}"
        for c in lines
    ]
    return ASS_HEADER + "\n".join(events) + "\n"


def _ass_time(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


class FfmpegMontage:
    async def seconds(self, media: Path) -> float:
        out = await run(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(media),
        )  # fmt: skip
        return float(out)

    async def stills(self, video: Path, count: int, out_dir: Path) -> list[Path]:
        await run(*stills_args(video, count, await self.seconds(video), out_dir))
        return await asyncio.to_thread(lambda: sorted(out_dir.glob("*.png")))

    async def render(self, cut: Cut, out: Path) -> Path:
        await run(*ffmpeg_args(cut, out))
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
