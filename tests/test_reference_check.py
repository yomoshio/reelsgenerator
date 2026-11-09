import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("cv2")
pytest.importorskip("scipy")

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "reference_check.py"
_spec = importlib.util.spec_from_file_location("reference_check", SCRIPT)
assert _spec
assert _spec.loader
rc = importlib.util.module_from_spec(_spec)
sys.modules["reference_check"] = rc
_spec.loader.exec_module(rc)

# What the script measured on 2026-11-08: the reference, part 3, and our Flood-1.
REFERENCE = {
    "duration": 92.267,
    "scenes": 15,
    "scene_len_median": 5.667,
    "scenes_7s": 5,
    "transitions": 11,
    "brightness_median": 26.87,
    "motion_median": 1.346,
    "motion_max": 3.633,
    "silence_longest": 0.04,
    "pause_median": 0.495,
    "pause_longest": 0.92,
    "bed_silent_share": 0.00926,
    "lufs": -15.5,
    "sample_rate": 44100,
    "channels": 2,
}
FLOOD_1 = {
    "duration": 83.667,
    "scenes": 26,
    "scene_len_median": 3.267,
    "scenes_7s": 0,
    "transitions": 0,
    "brightness_median": 74.2,
    "motion_median": 3.091,
    "motion_max": 17.536,
    "silence_longest": 0.89,
    "pause_median": 0.79,
    "pause_longest": 1.86,
    "bed_silent_share": 0.1402,
    "lufs": -15.8,
    "sample_rate": 96000,
    "channels": 1,
}


def failed(values: dict[str, float]) -> list[str]:
    return [c.name for c in rc.checks(values) if not c.ok]


def test_the_reference_fails_only_on_the_audio_rate_tiktok_gave_it() -> None:
    assert failed(REFERENCE) == ["audio_rate"]


def test_flood_1_passes_only_its_length_and_loudness() -> None:
    passed = [c.name for c in rc.checks(FLOOD_1) if c.ok]

    assert passed == ["duration", "loudness"]
    assert len(rc.checks(FLOOD_1)) == 15


@pytest.mark.parametrize(
    ("name", "value", "ok"),
    [
        ("duration", 95.0, True),
        ("duration", 95.1, False),
        ("brightness_median", 17.9, False),
        ("pause_longest", 1.0, True),
        ("sample_rate", 48000, True),
    ],
)
def test_bands_are_inclusive(name: str, value: float, ok: bool) -> None:
    assert (name not in failed({**REFERENCE, "sample_rate": 48000, name: value})) is ok


@pytest.fixture(scope="module")
def three_still_scenes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three dark still scenes of 2 s with hard cuts, over a stereo 48 kHz tone."""
    out = tmp_path_factory.mktemp("synthetic") / "three.mp4"
    colours = ["0x0b0f17", "0x3a1010", "0x1a2a4a"]
    inputs = [
        arg for c in colours for arg in ("-f", "lavfi", "-i", f"color=c={c}:s=180x320:r=30:d=2")
    ]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs,
         "-f", "lavfi", "-i", "sine=f=220:sample_rate=48000:d=6",
         "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v];[3:a]aformat=channel_layouts=stereo[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(out)],
        check=True,
    )  # fmt: skip
    return out


def test_counts_hard_cuts_between_still_scenes(three_still_scenes: Path) -> None:
    stats = rc.video_stats(three_still_scenes, None)

    assert stats["scenes"] == 3
    assert stats["transitions"] == 0
    assert stats["scene_len_median"] == pytest.approx(2.0, abs=0.05)
    assert stats["motion_max"] < 0.1


def test_reads_the_audio_format_and_finds_no_silence_under_a_steady_tone(
    three_still_scenes: Path,
) -> None:
    stats = rc.audio_stats(three_still_scenes)

    assert (stats["sample_rate"], stats["channels"]) == (48000, 2)
    assert stats["silence_longest"] < 0.15


# The videos are not in the repository. To check the script against them:
#   REFERENCE_VIDEO=~/Загрузки/<эталон>.mp4 FLOOD1_VIDEO=<Потоп-1>.mp4 pytest tests/test_reference_check.py
@pytest.mark.parametrize(("variable", "passing"), [("REFERENCE_VIDEO", 14), ("FLOOD1_VIDEO", 2)])
def test_measures_the_videos_of_the_spec(variable: str, passing: int) -> None:
    path = os.environ.get(variable)
    if not path:
        pytest.skip(f"{variable} is not set")
    video = Path(path).expanduser()
    results = rc.checks({**rc.video_stats(video, None), **rc.audio_stats(video)})

    assert sum(c.ok for c in results) == passing
