"""The render step: every beat to a clip, several beats at once.

A beat's frames come out of the runtime as raw RGBA and go straight into ffmpeg, which
burns in the captions and lays the beat's sound under them: the voice, the style's drone
ducked under it, and a short sound on every plate the style has one for. Frames never
touch the disk."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from reelsmith import runtime
from reelsmith.captions import FPS, HEIGHT, VOICE_CHAIN, WIDTH, Word, captions, to_ass
from reelsmith.jobs import Context, Job
from reelsmith.scenes import Timing, carried, timings
from reelsmith.settings import Settings
from reelsmith.story import Beat, Episode
from reelsmith.styles import Style
from reelsmith.text import bare

SFX_LEVEL = 0.4  # about 8 dB under the voice
BED_LEVEL = 0.35
BED_FLOOR = 0.25  # the bed is never ducked deeper than 12 dB


STUCK_BASE = 180.0  # seconds a beat may take to draw whatever its length
STUCK_PER_SECOND = 30.0


class RenderError(Exception):
    pass


def room(folder: Path, settings: Settings) -> None:
    """Refuses to start when the disk is nearly full: a stopped render leaves half-written
    clips, and a full disk breaks everything else on the machine."""
    free = shutil.disk_usage(folder).free / 1e9
    if free < settings.min_free_gb:
        raise RenderError(
            f"only {free:.1f} GB free under {folder}; rendering needs {settings.min_free_gb:g} GB"
        )


def accented(beat: Beat, words: list[Word]) -> list[Word]:
    """The words that bring up a plate are said with stress, and captions show them larger."""
    keys = {bare(r.on_word) for r in beat.reveals}
    return [Word(w.text, w.start, w.end, bare(w.text) in keys) for w in words]


def reveal_times(beat: Beat, words: list[Word]) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for r in beat.reveals:
        seen = 0
        for w in words:
            if bare(w.text) == bare(r.on_word):
                seen += 1
                if seen == r.occurrence:
                    found.append((r.kind, w.start))
                    break
    return found


def mix_args(
    voice: Path, bed: Path | None, sounds: list[tuple[Path, float]], seconds: float, out: Path
) -> list[str]:
    """The voice, the bed from the first frame to the last ducked softly under the voice,
    and each sound at its plate."""
    d = f"{seconds:.3f}"
    inputs = ["-i", str(voice)]
    graph = [
        f"[0:a]aresample=48000,aformat=channel_layouts=stereo,{VOICE_CHAIN},"
        f"apad=whole_dur={d},atrim=duration={d},asplit=2[voice][key]"
    ]
    mixed = ["[voice]"]
    n = 1
    if bed is not None:
        inputs += ["-stream_loop", "-1", "-i", str(bed)]
        graph += [
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={d},"
            f"volume={BED_LEVEL},asplit=2[bed][floor]",
            "[bed][key]sidechaincompress=threshold=0.05:ratio=3.5:attack=30:release=500[ducked]",
            f"[floor]volume={BED_FLOOR}[low]",
        ]
        mixed += ["[ducked]", "[low]"]
        n = 2
    else:
        graph.append("[key]anullsink")
    for k, (path, at) in enumerate(sounds):
        inputs += ["-i", str(path)]
        ms = max(round(at * 1000), 0)
        graph.append(
            f"[{n + k}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"adelay={ms}|{ms},volume={SFX_LEVEL}[s{k}]"
        )
        mixed.append(f"[s{k}]")
    graph.append(
        f"{''.join(mixed)}amix=inputs={len(mixed)}:duration=longest:normalize=0,"
        f"apad=whole_dur={d},atrim=duration={d}[audio]"
    )
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(graph), "-map", "[audio]", "-ar", "48000", "-ac", "2",
            str(out)]  # fmt: skip


def encode_args(captions_file: str, fonts: Path, audio: Path, out: Path) -> list[str]:
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
            "-i", "pipe:0", "-i", str(audio),
            "-vf", f"ass=filename={captions_file}:fontsdir={fonts}",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(out)]  # fmt: skip


async def run(args: list[str], cwd: Path | None = None) -> None:
    process = await asyncio.create_subprocess_exec(*args, cwd=cwd, stderr=asyncio.subprocess.PIPE)
    _, err = await process.communicate()
    if process.returncode:
        raise RenderError(f"{args[0]} failed: {err.decode().strip()[-400:]}")


async def render_beat(
    settings: Settings, style: Style, ep: Episode, n: int, *, timing: Timing, folder: Path
) -> Path:
    beat = ep.beats[n]
    name = f"beat{n + 1:02d}"
    clips = folder / "clips"
    clips.mkdir(exist_ok=True)
    (clips / f"{name}.ass").write_text(
        to_ass(captions(accented(beat, timing.words), max_words=style.captions.words), style),
        encoding="utf-8",
    )
    sounds = [
        (sfx, at)
        for kind, at in reveal_times(beat, timing.words)
        if (sfx := style.file(f"sfx/{kind}.wav")) is not None
    ]
    audio = clips / f"{name}.wav"
    voice = folder / "voice" / f"{name}.wav"
    await run(mix_args(voice, style.file(style.bed), sounds, timing.seconds, audio))
    code = (folder / "scenes" / f"{name}.js").read_text(encoding="utf-8")
    data = runtime.scene_input(
        ep, n, code=code, words=timing.words, seconds=timing.seconds, style=style,
        settings=settings, carried=carried(ep, n), mode="frames",
    )  # fmt: skip
    out = clips / f"{name}.mp4"
    fonts = (settings.runtime / "fonts").resolve()
    read, write = os.pipe()
    node = await asyncio.create_subprocess_exec(
        *runtime.command(settings),
        stdin=asyncio.subprocess.PIPE,
        stdout=write,
        stderr=asyncio.subprocess.PIPE,
    )
    os.close(write)
    encoder = await asyncio.create_subprocess_exec(
        *encode_args(f"{name}.ass", fonts, audio.resolve(), out.resolve()),
        stdin=read,
        cwd=clips,
        stderr=asyncio.subprocess.PIPE,
    )
    os.close(read)

    async def drawn() -> tuple[bytes, bytes]:
        _, node_err = await node.communicate(json.dumps(data, ensure_ascii=False).encode())
        _, encode_err = await encoder.communicate()
        return node_err, encode_err

    # A scene's own drawing can stall inside the canvas, where the runtime's clock does not
    # reach it. A beat draws in a few times its length; one far past that is stuck.
    limit = STUCK_BASE + STUCK_PER_SECOND * timing.seconds
    try:
        node_err, encode_err = await asyncio.wait_for(drawn(), limit)
    except TimeoutError:
        for process in (node, encoder):
            if process.returncode is None:
                process.kill()
            await process.wait()
        raise RenderError(
            f"beat {n + 1} was still drawing after {limit:.0f} s: its scene is stuck"
        ) from None
    if node.returncode:
        raise RenderError(f"beat {n + 1} did not draw: {node_err.decode().strip()[-400:]}")
    if encoder.returncode:
        raise RenderError(f"beat {n + 1} did not encode: {encode_err.decode().strip()[-400:]}")
    return out


async def render(job: Job, folder: Path, ctx: Context) -> None:
    """The render step: clips/beatNN.mp4 for every beat, as many at once as there are
    cores to spare: each beat takes one core to draw and about one more to encode."""
    room(folder, ctx.settings)
    style = ctx.styles.get(job.style)
    ep = Episode.model_validate_json((folder / "episode.json").read_text(encoding="utf-8"))
    beats = timings(folder)
    gate = asyncio.Semaphore(max(ctx.settings.cores() // 2, 1))

    async def one(n: int) -> Path:
        async with gate:
            return await render_beat(ctx.settings, style, ep, n, timing=beats[n], folder=folder)

    await asyncio.gather(*(one(n) for n in range(len(ep.beats))))
