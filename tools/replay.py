"""Draws again every scene the coder ever wrote for the given jobs and says what the runtime
makes of each today. The tries kept in scenes/beatNN.json are real answers of a real model:
after a change to the runtime this shows how many of them it now accepts, with no model and
no server.

    python tools/replay.py jobs/1120-b59eae jobs/1120-2d7da3 [--first] [--show] [--keep DIR]
"""

import argparse
import asyncio
import collections
import json
import re
import tempfile
from pathlib import Path

from reelsmith import runtime
from reelsmith.scenes import carried, timings
from reelsmith.settings import Settings
from reelsmith.story import Episode
from reelsmith.styles import Styles


async def replay(
    folder: Path, *, first: bool, show: bool, keep: Path | None, kinds: collections.Counter[str]
) -> tuple[int, int]:
    settings = Settings()
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    style = Styles(settings.styles).get(job["style"])
    ep = Episode.model_validate_json((folder / "episode.json").read_text(encoding="utf-8"))
    beats = timings(folder)
    clean = total = 0
    with tempfile.TemporaryDirectory() as scratch:
        out = keep / folder.name if keep else Path(scratch)
        for n, timing in enumerate(beats):
            report = folder / "scenes" / f"beat{n + 1:02d}.json"
            if not report.is_file():
                continue
            tries = json.loads(report.read_text(encoding="utf-8")).get("tries", [])
            for k, tried in enumerate(tries[:1] if first else tries, 1):
                if not tried["code"]:
                    continue
                data = runtime.scene_input(
                    ep, n, code=tried["code"], words=timing.words, seconds=timing.seconds,
                    style=style, settings=settings, carried=carried(ep, n),
                    keys=[0.4, timing.seconds / 2, max(timing.seconds - 0.3, 0.5)],
                    out=out / f"beat{n + 1:02d}-{k}",
                )  # fmt: skip
                faults = (await runtime.keys(settings, data)).faults()
                total += 1
                clean += not faults
                for fault in faults:
                    kinds[re.sub(r"«[^»]*»|'[^']*'|`[^`]*`|\d+(\.\d+)?", "_", fault)[:60]] += 1
                if show:
                    print(
                        f"{folder.name} beat {n + 1} try {k}: {'; '.join(faults)[:300] or 'clean'}"
                    )
    return clean, total


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("jobs", nargs="+", type=Path)
    parser.add_argument("--first", action="store_true", help="only the first try of every beat")
    parser.add_argument("--show", action="store_true", help="every try with its faults")
    parser.add_argument("--keep", type=Path, help="keep the keyframes in this folder")
    args = parser.parse_args()
    kinds: collections.Counter[str] = collections.Counter()
    clean = total = 0
    for folder in args.jobs:
        c, t = await replay(folder, first=args.first, show=args.show, keep=args.keep, kinds=kinds)
        clean, total = clean + c, total + t
    print(f"{clean} of {total} scenes draw clean")
    for kind, count in kinds.most_common(30):
        print(f"{count:4d}  {kind}")


if __name__ == "__main__":
    asyncio.run(main())
