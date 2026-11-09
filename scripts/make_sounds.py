"""Stand-in sounds for a series library, made by ffmpeg from tones and noise, until the
library gets its CC0 recordings. Writes sfx/<key>.wav for every sound of library.toml that
has no file yet, bed/<location>.wav for every location and bed/drone.wav.

    python scripts/make_sounds.py studio/series/proto
    python scripts/make_sounds.py studio/series/proto --force   # remake the ones there are
"""

import argparse
import subprocess
import tomllib
from pathlib import Path

BED_SECONDS = 30
POP = "aevalsrc='0.7*sin(2*PI*(500+900*exp(-30*t))*t)*exp(-25*t)':d=0.18"
KNOCK = (
    "aevalsrc='0.9*sin(2*PI*190*t)*exp(-28*t)+0.5*sin(2*PI*510*t)*exp(-40*t)"
    "+0.3*sin(2*PI*1270*t)*exp(-60*t)':d=0.5"
)
SOUNDS = {
    "pipe_knock": KNOCK,
    "pipe_knock_muffled": KNOCK + ",lowpass=f=450,volume=1.2",
    "card_pop": POP,
    "cloth_wrap": "anoisesrc=color=pink:d=0.7:a=0.6,bandpass=f=1800:width_type=h:w=1400,volume=4,"
    "afade=t=in:d=0.15,afade=t=out:st=0.35:d=0.35",
    "ui_confirm": "aevalsrc='0.5*sin(2*PI*660*t)*lt(t,0.09)+0.5*sin(2*PI*990*t)*gte(t,0.1)"
    "*lt(t,0.22)':d=0.3",
    "ui_tick": "aevalsrc='0.6*sin(2*PI*2200*t)*exp(-120*t)':d=0.08",
    "stamp_hit": "aevalsrc='sin(2*PI*70*t)*exp(-18*t)+0.4*(random(0)*2-1)*exp(-50*t)':d=0.45",
    "alarm_beep": "aevalsrc='0.5*sin(2*PI*1250*t)*lt(mod(t,0.2),0.1)*lt(t,0.6)':d=0.65",
    "glitch": "anoisesrc=d=0.25:a=0.5,tremolo=f=40:d=1,highpass=f=800",
}
AMBIENT = (
    f"anoisesrc=color=brown:d={BED_SECONDS}:a=0.6,lowpass=f=260,volume=0.7[n];"
    f"sine=f=50:d={BED_SECONDS},volume=0.04[h];[n][h]amix=inputs=2:normalize=0"
)
# A pitched drone reads as a voice to the pause detector of tools/reference_check.py, which
# looks for a period between 70 and 400 Hz: the tone stays below, the hum above is noise.
DRONE = (
    f"aevalsrc='0.3*sin(2*PI*41.2*t)*(0.8+0.2*sin(2*PI*0.13*t))':d={BED_SECONDS}[t];"
    f"anoisesrc=color=brown:d={BED_SECONDS}:a=0.8,bandpass=f=150:width_type=h:w=120,"
    "volume=3[n];[t][n]amix=inputs=2:normalize=0"
)


def make(graph: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-filter_complex",
         f"{graph}[o]", "-map", "[o]", "-ar", "48000", "-ac", "2", str(out)],
        check=True,
    )  # fmt: skip
    print(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    library = tomllib.loads((args.series / "library.toml").read_text(encoding="utf-8"))
    wanted = {
        **{args.series / "sfx" / f"{k}.wav": SOUNDS.get(k, POP) for k in library.get("sfx", {})},
        **{args.series / "bed" / f"{k}.wav": AMBIENT for k in library["locations"]},
        args.series / "bed" / "drone.wav": DRONE,
    }
    for out, graph in wanted.items():
        if args.force or not out.exists():
            make(graph, out)


if __name__ == "__main__":
    main()
