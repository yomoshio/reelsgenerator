"""The Python side of the JS runtime in `runtime/`: what a beat's input looks like, running
it for keyframes and a report, the command that streams its frames, and the catalog the
director and the coder choose from.

Scene code is written by a model, so Node runs it under its permission model: it may read
the runtime, the thing library and the font, write only the folder of its keyframes, and
start no processes. The code itself runs in a `vm` context without require or process."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from reelsmith.captions import FPS, Word
from reelsmith.catalog import Catalog
from reelsmith.settings import Settings
from reelsmith.story import Beat, Episode, Reveal
from reelsmith.styles import Style

HEAP_MB = 512
KEYS_TIMEOUT = 120.0


@dataclass
class Report:
    ok: bool
    error: str | None
    problems: list[str] = field(default_factory=list)
    pngs: list[Path] = field(default_factory=list)
    graph: list[dict[str, Any]] = field(default_factory=list)

    def faults(self) -> list[str]:
        return [self.error] if self.error else list(self.problems)


def scene_input(
    ep: Episode,
    n: int,
    *,
    code: str,
    words: Sequence[Word],
    seconds: float,
    style: Style,
    settings: Settings,
    carried: Sequence[Reveal] = (),
    mode: Literal["keys", "frames"] = "keys",
    keys: Sequence[float] = (),
    out: Path | None = None,
) -> dict[str, Any]:
    beat: Beat = ep.beats[n]
    return {
        "mode": mode,
        "code": code,
        "beat": beat.model_dump(),
        "place": ep.place(beat.place).model_dump(),
        "characters": [c.model_dump() for c in ep.characters],
        "palette": style.palette,
        "fonts": {"plate": str(font(settings, style))},
        "words": [{"text": w.text, "start": w.start, "end": w.end} for w in words],
        "seconds": round(seconds, 3),
        "fps": FPS,
        "keys": list(keys),
        "out": str(out) if out else "",
        "library": str(settings.library.resolve()),
        "carried": [r.model_dump() for r in carried],
    }


def font(settings: Settings, style: Style) -> Path:
    for folder in (style.folder, settings.runtime / "fonts"):
        if (folder / style.fonts.plate).is_file():
            return (folder / style.fonts.plate).resolve()
    raise FileNotFoundError(f"no font {style.fonts.plate} in {style.folder} or runtime/fonts")


def command(settings: Settings, writes: Path | None = None) -> list[str]:
    runtime = settings.runtime.resolve()
    reads = [runtime, settings.library.resolve(), *(p.resolve() for p in [settings.styles])]
    args = ["node", "--permission", "--allow-addons", "--no-warnings"]
    args += [f"--allow-fs-read={p}" for p in reads]
    if writes is not None:
        args.append(f"--allow-fs-write={writes.resolve()}")
    return [*args, f"--max-old-space-size={HEAP_MB}", str(runtime / "src" / "run.mjs")]


async def keys(settings: Settings, data: dict[str, Any]) -> Report:
    """Keyframes of a beat as PNGs next to `data["out"]` and what is wrong with them."""
    out = Path(data["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        *command(settings, out.parent),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(data, ensure_ascii=False).encode()), KEYS_TIMEOUT
        )
    except TimeoutError:
        process.kill()
        return Report(False, f"the scene took longer than {KEYS_TIMEOUT:.0f} s to draw")
    lines = stdout.decode().strip().splitlines()
    if not lines:
        tail = stderr.decode().strip().splitlines()[-1:] or [f"exit {process.returncode}"]
        cause = "ran out of memory" if "heap" in stderr.decode().lower() else tail[0]
        return Report(False, f"the scene crashed: {cause}")
    raw = json.loads(lines[-1])
    return Report(
        ok=raw["ok"],
        error=raw["error"],
        problems=raw["problems"],
        pngs=[Path(p) for p in raw["pngs"]],
        graph=raw["graph"],
    )


def catalog(settings: Settings) -> Catalog:
    """The default catalog and every thing in the library."""
    made = Catalog()
    if settings.library.is_dir():
        index = settings.library / "index.json"
        about = json.loads(index.read_text(encoding="utf-8")) if index.is_file() else {}
        for svg in sorted(settings.library.glob("*.svg")):
            made.things.setdefault(svg.stem, about.get(svg.stem, {}).get("about", svg.stem))
    return made
