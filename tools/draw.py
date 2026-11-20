"""Draws one beat of a job from its scene file and says what the runtime makes of it: the
keyframes as PNGs next to the scene, the faults, and what the runtime left out.

    python tools/draw.py jobs/1120-73a578 3            scenes/beat03.js -> scenes/beat03-0..2.png
    python tools/draw.py jobs/1120-73a578 3 --at 1.5 4 keyframes at these seconds instead

For writing a scene by hand, or by a model that looks at its own pictures."""

import argparse
import asyncio
import json
from pathlib import Path

from reelsmith import runtime
from reelsmith.scenes import brief, carried, timings
from reelsmith.settings import Settings
from reelsmith.story import Episode
from reelsmith.styles import Styles


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("job", type=Path)
    parser.add_argument("beat", type=int)
    parser.add_argument("--at", type=float, nargs="+", help="seconds of the keyframes")
    parser.add_argument("--brief", action="store_true", help="print the beat's task and stop")
    args = parser.parse_args()
    settings = Settings()
    job = json.loads((args.job / "job.json").read_text(encoding="utf-8"))
    style = Styles(settings.styles).get(job["style"])
    ep = Episode.model_validate_json((args.job / "episode.json").read_text(encoding="utf-8"))
    n = args.beat - 1
    timing = timings(args.job)[n]
    if args.brief:
        print(brief(ep, n, timing, {}, ""))
        return
    name = f"beat{args.beat:02d}"
    code = (args.job / "scenes" / f"{name}.js").read_text(encoding="utf-8")
    keys = args.at or [0.4, timing.seconds / 2, max(timing.seconds - 0.3, 0.5)]
    data = runtime.scene_input(
        ep, n, code=code, words=timing.words, seconds=timing.seconds, style=style,
        settings=settings, carried=carried(ep, n), keys=keys, out=args.job / "scenes" / name,
    )  # fmt: skip
    process = await asyncio.create_subprocess_exec(
        *runtime.command(settings, args.job / "scenes"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await process.communicate(json.dumps(data, ensure_ascii=False).encode())
    raw = json.loads(out.decode().strip().splitlines()[-1])
    print(f"{name}, {timing.seconds:.1f} s")
    print("error:", raw["error"])
    for fault in raw["problems"]:
        print("fault:", fault)
    for left in raw.get("ignored", []):
        print("left out:", left)
    for png in raw["pngs"]:
        print("drew:", png)


if __name__ == "__main__":
    asyncio.run(main())
