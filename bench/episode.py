"""Joins clips a video model made into an episode with the narrator's voice and captions.

    python bench/episode.py jobs/1125-68dbbb bench/out/episode --out outbox/episode.mp4

The job gives the voice of every beat and when each word is said (voice/beatNN.wav and
voice/timing.json); the clips folder gives beatNN.mp4, one for a beat. A clip is cut to its
beat, or holds its last frame if it is short. Whatever sound the model made stays under the
voice, quietly. Captions show three words at a time, the one being said in yellow."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

WIDTH, HEIGHT, FPS = 1080, 1920, 24
MOST_WORDS, MOST_LETTERS = 3, 20
FIELDS = (
    "Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, "
    "Outline, Shadow, Alignment, MarginL, MarginR, MarginV"
)
HEAD = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2

[V4+ Styles]
Format: {FIELDS}
Style: Said,Montserrat ExtraBold,84,&H00FFFFFF,&H00101010,&H80000000,0,1,7,3,2,60,60,470

[Events]
Format: Layer, Start, End, Style, Text
"""


def stamp(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{seconds - whole // 60 * 60:05.2f}"


def phrases(words: list[dict]) -> list[list[dict]]:
    """Words in runs short enough to read at a glance; a run ends at a full stop or comma."""
    out: list[list[dict]] = [[]]
    for word in words:
        run = out[-1]
        letters = sum(len(w["text"]) for w in run) + len(word["text"])
        if run and (len(run) == MOST_WORDS or letters > MOST_LETTERS):
            out.append(run := [])
        run.append(word)
        if word["text"][-1] in ".,!?…:;":
            out.append([])
    return [run for run in out if run]


def captions(beats: list[dict]) -> str:
    lines, at = [], 0.0
    for beat in beats:
        for run in phrases(beat["words"]):
            for n, word in enumerate(run):
                until = run[n + 1]["start"] if n + 1 < len(run) else word["end"] + 0.12
                text = " ".join(
                    f"{{\\c&H0038D8FF&}}{w['text']}{{\\c&H00FFFFFF&}}" if w is word else w["text"]
                    for w in run
                )
                lines.append(
                    f"Dialogue: 0,{stamp(at + word['start'])},{stamp(at + until)},Said,{text}"
                )
        at += beat["seconds"]
    return HEAD + "\n".join(lines) + "\n"


def sounds(clip: Path) -> bool:
    asked = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", str(clip)]  # fmt: skip
    return bool(subprocess.run(asked, capture_output=True, text=True, check=True).stdout.strip())


def beat_args(clip: Path, voice: Path, seconds: float, ambient: float, out: Path) -> list[str]:
    picture = (
        f"[0:v]fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={WIDTH}:{HEIGHT},tpad=stop_mode=clone:stop_duration={seconds},"
        f"trim=duration={seconds},setsar=1[v]"
    )
    said = f"[1:a]aresample=48000,apad,atrim=duration={seconds}[said]"
    if ambient and sounds(clip):
        under = f"[0:a]aresample=48000,volume={ambient},apad,atrim=duration={seconds}[under]"
        sound = f"{said};{under};[said][under]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        sound = said.replace("[said]", "[a]")
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(clip), "-i", str(voice),
            "-filter_complex", f"{picture};{sound}", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "14", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le", "-ac", "2", str(out)]  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("job", type=Path)
    parser.add_argument("clips", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ambient", type=float, default=0.15, help="the model's sound, 0 is off")
    args = parser.parse_args()
    beats = json.loads((args.job / "voice" / "timing.json").read_text(encoding="utf-8"))["beats"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        parts = []
        for n, beat in enumerate(beats, 1):
            clip = next(iter(sorted(args.clips.glob(f"beat{n:02d}.*"))), None)
            if clip is None:
                raise SystemExit(f"no clip for beat {n} in {args.clips}")
            part = Path(work) / f"{n:02d}.mkv"
            voice = args.job / "voice" / f"beat{n:02d}.wav"
            subprocess.run(beat_args(clip, voice, beat["seconds"], args.ambient, part), check=True)
            parts.append(part)
        listing = Path(work) / "parts.txt"
        listing.write_text("".join(f"file '{part}'\n" for part in parts), encoding="utf-8")
        script = Path(work) / "said.ass"
        script.write_text(captions(beats), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-vf", f"ass={script}", "-c:v", "libx264", "-crf", "16",
             "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(args.out)],
            check=True,
        )  # fmt: skip
    print(args.out)


if __name__ == "__main__":
    main()
