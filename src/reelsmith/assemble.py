"""The assemble step: the beats joined into one video, the closing card, the music, one
loudness, and the measures against the reference.

Beats are joined by a short pixel dissolve over the cut and a crossfade of their sound,
the way the reference changes scenes. When the episode goes on, a closing card asks its
question in silence at the end. The music of the style runs under everything. The clips
are deleted once the video is made and measured; the keyframes and the scene code stay."""

import asyncio
import json
import sys
from pathlib import Path

from reelsmith import runtime
from reelsmith.captions import FPS, HEIGHT, LOUDNESS, WIDTH
from reelsmith.jobs import Context, Job
from reelsmith.render import RenderError, room, run
from reelsmith.scenes import timings
from reelsmith.settings import Settings
from reelsmith.story import Episode
from reelsmith.styles import Style

JOIN = 0.25  # seconds of every dissolve between beats
CARD_SECONDS = 1.6
MUSIC_LEVEL = 0.16
CHECK = Path(__file__).parents[2] / "tools" / "reference_check.py"


def frames_seconds(seconds: float) -> float:
    return round(seconds * FPS) / FPS


def join_args(clips: list[Path], lengths: list[float], music: Path | None, out: Path) -> list[str]:
    """Clips dissolved into each other, their sound crossfaded, the music under it all and
    one loudness for the whole video."""
    inputs = [arg for clip in clips for arg in ("-i", str(clip))]
    graph = []
    video, audio = "[0:v]", "[0:a]"
    elapsed = lengths[0]
    for k in range(1, len(clips)):
        offset = elapsed - JOIN
        graph.append(
            f"{video}[{k}:v]xfade=transition=pixelize:duration={JOIN}:offset={offset:.3f}[v{k}]"
        )
        graph.append(f"{audio}[{k}:a]acrossfade=d={JOIN}[a{k}]")
        video, audio = f"[v{k}]", f"[a{k}]"
        elapsed += lengths[k] - JOIN
    total = f"{elapsed:.3f}"
    if music is not None:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        graph.append(
            f"[{len(clips)}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"atrim=duration={total},afade=t=out:st={max(elapsed - 1.5, 0):.3f}:d=1.5,"
            f"volume={MUSIC_LEVEL}[music]"
        )
        graph.append(f"{audio}[music]amix=inputs=2:duration=first:normalize=0[mixed]")
        audio = "[mixed]"
    graph.append(f"{audio}{LOUDNESS},aresample=48000[audio]")
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(graph), "-map", video, "-map", "[audio]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(out)]  # fmt: skip


async def card(settings: Settings, style: Style, ep: Episode, out: Path) -> Path:
    """The closing card with the next part's question, silent, as a clip."""
    data = {
        "mode": "card",
        "card": {"part": ep.part + 1, "text": ep.cliffhanger},
        "palette": style.palette,
        "fonts": {"plate": str(runtime.font(settings, style))},
        "seconds": CARD_SECONDS,
        "fps": FPS,
    }
    node = await asyncio.create_subprocess_exec(
        *runtime.command(settings),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    frames, err = await node.communicate(json.dumps(data, ensure_ascii=False).encode())
    if node.returncode:
        raise RenderError(f"the closing card did not draw: {err.decode()[-300:]}")
    encoder = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
        "-i", "pipe:0", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={CARD_SECONDS}",
        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(out),
        stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    _, err = await encoder.communicate(frames)
    if encoder.returncode:
        raise RenderError(f"the closing card did not encode: {err.decode()[-300:]}")
    return out


def joins(lengths: list[float]) -> list[float]:
    """The second every dissolve between two clips is half done."""
    out, elapsed = [], 0.0
    for length in lengths[:-1]:
        elapsed += length - JOIN
        out.append(round(elapsed + JOIN / 2, 3))
    return out


async def measure(video: Path, out: Path, joined: list[float]) -> dict[str, object]:
    """The reference check of the video, kept in check.json; its absence is not fatal."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(CHECK), str(video), "--json",
        "--joins", ",".join(str(t) for t in joined),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    stdout, stderr = await process.communicate()
    try:
        found: dict[str, object] = json.loads(stdout)
    except json.JSONDecodeError:
        found = {"error": stderr.decode().strip()[-300:] or "no report"}
    await asyncio.to_thread(
        out.write_text, json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return found


async def assemble(job: Job, folder: Path, ctx: Context) -> None:
    room(folder, ctx.settings)
    style = ctx.styles.get(job.style)
    ep = Episode.model_validate_json((folder / "episode.json").read_text(encoding="utf-8"))
    beats = timings(folder)
    clips = [folder / "clips" / f"beat{n:02d}.mp4" for n in range(1, len(ep.beats) + 1)]
    lengths = [frames_seconds(b.seconds) for b in beats]
    if ep.cliffhanger:
        clips.append(await card(ctx.settings, style, ep, folder / "clips" / "card.mp4"))
        lengths.append(CARD_SECONDS)
    final = folder / "final.mp4"
    await run(join_args(clips, lengths, style.file(style.music), final))
    found = await measure(final, folder / "check.json", joins(lengths))
    failed = [c["name"] for c in found.get("checks", []) if not c.get("ok")]  # type: ignore[attr-defined]
    job.note("assemble", note=f"reference check failed: {', '.join(failed)}" if failed else "")
    code = " ".join(p.read_text(encoding="utf-8") for p in (folder / "scenes").glob("*.js"))
    named = runtime.credits(ctx.settings, code)
    thanks = f"\nIcons: {', '.join(named)}\n" if named else ""
    (folder / "post.txt").write_text(f"{ep.title}\n\n{ep.premise}\n{thanks}", encoding="utf-8")
    for leftover in (folder / "clips").glob("*"):
        if leftover.suffix in {".mp4", ".wav"}:
            leftover.unlink()
