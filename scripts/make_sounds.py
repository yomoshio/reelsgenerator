"""Stand-in sounds for a style, made by ffmpeg from tones and noise, until the style gets
its CC0 recordings: the drone under every beat, and sfx/<kind>.wav for every kind of plate
that has no file yet.

    python scripts/make_sounds.py styles/blackout
    python scripts/make_sounds.py styles/blackout --force   # remake the ones there are
"""

import argparse
import subprocess
from pathlib import Path

BED_SECONDS = 30
POP = "aevalsrc='0.7*sin(2*PI*(500+900*exp(-30*t))*t)*exp(-25*t)':d=0.18"
PLATES = {
    "rule_card": POP,
    "hud": "aevalsrc='0.6*sin(2*PI*2200*t)*exp(-120*t)':d=0.08",
    "label": POP,
    "status": "aevalsrc='0.5*sin(2*PI*660*t)*lt(t,0.09)+0.5*sin(2*PI*990*t)*gte(t,0.1)"
    "*lt(t,0.22)':d=0.3",
    "stamp": "aevalsrc='sin(2*PI*70*t)*exp(-18*t)+0.4*(random(0)*2-1)*exp(-50*t)':d=0.45",
    "count": "aevalsrc='0.6*sin(2*PI*2200*t)*exp(-120*t)':d=0.08",
}
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
    parser.add_argument("style", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    wanted = {
        **{args.style / "sfx" / f"{kind}.wav": graph for kind, graph in PLATES.items()},
        args.style / "drone.wav": DRONE,
    }
    for out, graph in wanted.items():
        if args.force or not out.exists():
            make(graph, out)


if __name__ == "__main__":
    main()
