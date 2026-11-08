"""Measure a finished video against the reference format and fail if it drifts.

    python tools/reference_check.py final.mp4            # human-readable table, exit 1 on failure
    python tools/reference_check.py final.mp4 --json     # machine-readable report
    python tools/reference_check.py final.mp4 --sheet sheet.jpg

Needs ffmpeg on PATH, numpy, scipy and opencv-python-headless. Runs on CPU,
about a minute for a 90 s video.
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from scipy import signal

GRID_W, GRID_H = 180, 320  # analysis size; motion is reported in pixels of this grid
SCENE_TOP = 0.55  # subtitles live below this line and change every few words
TRANSITION_MAX = 0.5  # segments shorter than this are transitions, not scenes


@dataclass(frozen=True)
class Check:
    name: str
    value: float
    low: float | None
    high: float | None
    unit: str = ""

    @property
    def ok(self) -> bool:
        return (self.low is None or self.value >= self.low) and (
            self.high is None or self.value <= self.high
        )


# Bands come from "Blackout on the 32nd floor", part 3. Widen them once more parts are measured.
def checks(v: dict[str, float]) -> list[Check]:
    return [
        Check("duration", v["duration"], 60, 95, "s"),
        Check("scenes", v["scenes"], 10, 18),
        Check("scene_len_median", v["scene_len_median"], 4.5, 7.5, "s"),
        Check("scenes_7s_or_longer", v["scenes_7s"], 4, None),
        Check("transitions", v["transitions"], 6, None),
        Check("brightness_median", v["brightness_median"], 18, 40, "/255"),
        Check("motion_median", v["motion_median"], None, 2.0, "px/s"),
        Check("motion_max", v["motion_max"], None, 5.0, "px/s"),
        Check("silence_longest", v["silence_longest"], None, 0.15, "s"),
        Check("pause_median", v["pause_median"], None, 0.6, "s"),
        Check("pause_longest", v["pause_longest"], None, 1.0, "s"),
        Check("bed_below_-50dB", v["bed_silent_share"] * 100, None, 2.0, "%"),
        Check("loudness", v["lufs"], -16.0, -14.0, "LUFS"),
        Check("audio_rate", v["sample_rate"], 48000, 48000, "Hz"),
        Check("audio_channels", v["channels"], 2, 2),
    ]


def video_stats(path: Path, sheet: Path | None) -> dict[str, float]:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    top = int(GRID_H * SCENE_TOP)
    gray, hists = [], []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [16, 8, 8], [0, 180, 0, 256, 0, 256])
        hists.append(cv2.normalize(hist, hist).flatten())
        gray.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)[:top])

    cuts = [0]
    for i in range(1, len(gray)):
        hist_jump = cv2.compareHist(hists[i - 1], hists[i], cv2.HISTCMP_BHATTACHARYYA)
        pixel_jump = float(np.mean(np.abs(gray[i].astype(np.float32) - gray[i - 1])))
        if (hist_jump > 0.35 or pixel_jump > 28) and i - cuts[-1] >= 6:
            cuts.append(i)
    cuts.append(len(gray))

    lengths, motion, brightness = [], [], []
    for start, end in itertools.pairwise(cuts):
        length = (end - start) / fps
        brightness.append(float(np.mean(gray[(start + end) // 2])))
        if length < TRANSITION_MAX:
            continue
        lengths.append(length)
        motion.append(_scene_motion(gray, start, end, fps))
    transitions = len(cuts) - 1 - len(lengths)

    if sheet is not None:
        _contact_sheet(path, cuts, fps, sheet)

    lengths_arr = np.array(lengths)
    return {
        "duration": len(gray) / fps,
        "scenes": float(len(lengths)),
        "scene_len_median": float(np.median(lengths_arr)),
        "scenes_7s": float((lengths_arr >= 7).sum()),
        "transitions": float(transitions),
        "brightness_median": float(np.median(brightness)),
        "motion_median": float(np.median(motion)),
        "motion_max": float(np.max(motion)),
    }


def _scene_motion(gray: list[np.ndarray], start: int, end: int, fps: float) -> float:
    """Residual optical flow after removing a global zoom/pan: what moves inside the picture."""
    ys, xs = np.mgrid[0 : gray[0].shape[0] : 6, 0:GRID_W:6]
    src = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32)
    samples = list(range(start + 2, end - 2, 3))
    residuals = []
    for a, b in itertools.pairwise(samples):
        flow = cv2.calcOpticalFlowFarneback(gray[a], gray[b], None, 0.5, 3, 15, 3, 5, 1.2, 0)
        dst = src + flow[ys.ravel(), xs.ravel()]
        model, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
        if model is None:
            continue
        predicted = src @ model[:, :2].T + model[:, 2]
        residuals.append(float(np.mean(np.linalg.norm(dst - predicted, axis=1))))
    return float(np.mean(residuals)) / (3 / fps) if residuals else 0.0


def _contact_sheet(path: Path, cuts: list[int], fps: float, out: Path) -> None:
    cap = cv2.VideoCapture(str(path))
    thumbs = []
    for n, (start, end) in enumerate(itertools.pairwise(cuts), 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, (start + end) // 2)
        ok, frame = cap.read()
        if not ok:
            continue
        thumb = cv2.resize(frame, (216, 384), interpolation=cv2.INTER_AREA)
        cv2.rectangle(thumb, (0, 0), (96, 26), (0, 0, 0), -1)
        label = f"{n} {(end - start) / fps:.1f}s"
        cv2.putText(thumb, label, (4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        thumbs.append(thumb)
    while len(thumbs) % 8:
        thumbs.append(np.zeros_like(thumbs[0]))
    rows = [np.hstack(thumbs[i : i + 8]) for i in range(0, len(thumbs), 8)]
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 82])


def audio_stats(path: Path) -> dict[str, float]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    stream = json.loads(probe.stdout)["streams"][0]

    loud = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    lufs = float(loud.stderr.rsplit("I:", 1)[1].split("LUFS")[0])

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav),
            ],
            check=True,
        )
        with wave.open(str(wav)) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

    hop, win = int(0.010 * sr), int(0.030 * sr)
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    db = 20 * np.log10(np.sqrt(np.mean(frames**2, axis=1)) + 1e-9)
    voiced = _voiced(frames, sr, win)
    talking = signal.convolve(voiced.astype(float), np.ones(25), "same") > 0

    edges = np.diff(np.r_[0, talking.astype(int), 0])
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
    gaps = (starts[1:] - ends[:-1]) * hop / sr
    gaps = gaps[gaps > 0.3]

    # Silence anywhere except the last second, where a fade-out is fine.
    tail = len(db) - int(1.0 / 0.010)
    silent = db[:tail] < -50
    longest = 0
    run = 0
    for s in silent:
        run = run + 1 if s else 0
        longest = max(longest, run)

    return {
        "lufs": lufs,
        "sample_rate": float(stream["sample_rate"]),
        "channels": float(stream["channels"]),
        "pause_median": float(np.median(gaps)) if len(gaps) else 0.0,
        "pause_longest": float(gaps.max()) if len(gaps) else 0.0,
        "bed_silent_share": float(np.mean(db[~talking] < -50)),
        "silence_longest": longest * hop / sr,
    }


def _voiced(frames: np.ndarray, sr: int, win: int) -> np.ndarray:
    lo, hi = int(sr / 400), int(sr / 70)
    out = np.zeros(len(frames), bool)
    for i, raw in enumerate(frames):
        frame = raw - raw.mean()
        if np.sqrt(np.mean(frame**2)) < 0.01:
            continue
        ac = np.correlate(frame, frame, "full")[win - 1 :]
        ac /= ac[0] + 1e-12
        out[i] = ac[lo:hi].max() > 0.55
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sheet", type=Path)
    args = parser.parse_args()

    values = {**video_stats(args.video, args.sheet), **audio_stats(args.video)}
    results = checks(values)
    failed = [c for c in results if not c.ok]

    if args.json:
        report = {
            "ok": not failed,
            "checks": [asdict(c) | {"ok": c.ok} for c in results],
        }
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for c in results:
            band = f"{'' if c.low is None else c.low}..{'' if c.high is None else c.high}"
            mark = "ok  " if c.ok else "FAIL"
            print(f"{mark} {c.name:<22} {c.value:>9.2f} {c.unit:<5} want {band}")
        print(f"\n{len(results) - len(failed)}/{len(results)} checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
