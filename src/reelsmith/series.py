"""A synopsis becomes a serial: the season arc first, then a beat-by-beat outline for every
episode, written out as a bible for people and a file of episode ideas for `queue`."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reelsmith.models import Outline, Season
from reelsmith.styles import Style


class Planner(Protocol):
    async def season(self, synopsis: str, style: Style, episodes: int) -> Season: ...

    async def plan(self, idea: str, style: Style) -> Outline: ...


@dataclass(frozen=True)
class Serial:
    season: Season
    outlines: list[Outline]


async def make_serial(
    planner: Planner,
    synopsis: str,
    style: Style,
    episodes: int,
    progress: Callable[[str], None] = lambda _: None,
) -> Serial:
    season = await planner.season(synopsis, style, episodes)
    progress(f"season: {season.title}, {len(season.episodes)} episodes")
    outlines: list[Outline] = []
    for n in range(len(season.episodes)):
        outlines.append(await planner.plan(episode_brief(season, n), style))
        progress(f"episode {n + 1}: {outlines[-1].title}")
    return Serial(season, outlines)


def episode_brief(season: Season, n: int) -> str:
    """What the planner knows when it outlines episode `n`: the world, the people with
    their fixed looks, what the last two episodes were about, and this episode's logline."""
    episode = season.episodes[n]
    people = "; ".join(f"{c.name}: {c.look}" for c in season.characters)
    earlier = " ".join(
        f"Episode {i + 1}: {season.episodes[i].logline}" for i in range(max(n - 2, 0), n)
    )
    return (
        f"Series «{season.title}», episode {n + 1} of {len(season.episodes)}, «{episode.title}». "
        f"World: {season.world} Characters, copy their looks exactly: {people}. "
        f"{'Earlier: ' + earlier + ' ' if earlier else ''}This episode: {episode.logline}"
    )


def ideas_file(serial: Serial, style: str) -> str:
    total = len(serial.outlines)
    lines = [f"# «{serial.season.title}». One line, one episode: ./run.sh ideas ..."]
    for n, (episode, outline) in enumerate(
        zip(serial.season.episodes, serial.outlines, strict=True), 1
    ):
        lines.append(
            f"[{style}] «{serial.season.title}», episode {n} of {total}, «{episode.title}». "
            f"{outline.as_brief()}"
        )
    return "\n".join(lines) + "\n"


def bible(serial: Serial) -> str:
    season = serial.season
    people = "\n".join(f"| {c.name} | {c.look} |" for c in season.characters)
    rows = "\n".join(f"| {n} | {e.title} | {e.logline} |" for n, e in enumerate(season.episodes, 1))
    outlines = "\n\n".join(
        f"### {n}. {o.title}\n\n"
        + "\n".join(f"{i}. {beat}" for i, beat in enumerate(o.beats, 1))
        + f"\n\nDetail planted early: {o.planted}\n\nLast line: {o.ending}"
        for n, o in enumerate(serial.outlines, 1)
    )
    return (
        f"# {season.title}\n\n{season.world}\n\n## Characters\n\n| Name | Look |\n| --- | --- |\n"
        f"{people}\n\n## Episodes\n\n| # | Title | Logline |\n| --- | --- | --- |\n{rows}\n\n"
        f"## Outlines\n\n{outlines}\n"
    )


def outline_markdown(outline: Outline) -> str:
    people = "\n".join(f"- {c.name}: {c.look}" for c in outline.characters)
    beats = "\n".join(f"{n}. {beat}" for n, beat in enumerate(outline.beats, 1))
    return (
        f"**{outline.title}**\n\n{people}\n\n{beats}\n\n"
        f"Detail planted early: {outline.planted}\n\nLast line: {outline.ending}\n"
    )


def write_serial(serial: Serial, style: str, folder: Path, name: str) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    notes, queue = folder / f"{name}.md", folder / f"{name}.txt"
    notes.write_text(bible(serial), encoding="utf-8")
    queue.write_text(ideas_file(serial, style), encoding="utf-8")
    return notes, queue


def ideas(lines: Sequence[str]) -> list[tuple[int, str | None, str]]:
    """Line number, style or None, and idea for every line that is not empty or commented."""
    found: list[tuple[int, str | None, str]] = []
    for number, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        style, idea = None, line
        if line.startswith("[") and "]" in line:
            style, idea = line[1:].split("]", 1)
            style, idea = style.strip(), idea.strip()
        if idea:
            found.append((number, style, idea))
    return found
