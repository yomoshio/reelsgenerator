"""A finished story or a whole book becomes a serial that keeps the author's events.

The text is cut into passages the writer model can read at once, and each passage is
retold as the events that happen in it. The numbered events are split into episodes where
the story itself turns, never stretched to fill a count. Every episode then gets its own
events word for word, so the planner arranges them into beats and invents nothing.

Books come as plain text, FictionBook (.fb2, the usual format of Russian libraries) or
EPUB."""

import re
import zipfile
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Protocol
from xml.etree import ElementTree

from reelsmith.models import Adaptation, EpisodeIdea, Part, Season
from reelsmith.series import Planner, Serial, episode_brief
from reelsmith.styles import Style

PASSAGE = 10_000  # characters the writer model reads at once, with room for its answer
DIGEST = 16_000  # characters of numbered events the season planner reads at once
BOOKS = (".txt", ".md", ".fb2", ".epub")


class Adapter(Planner, Protocol):
    async def retell(self, passage: str) -> list[str]: ...

    async def adapt(self, events: list[str], style: Style, most: int) -> Adaptation: ...


async def make_adaptation(
    adapter: Adapter,
    text: str,
    style: Style,
    most: int,
    progress: Callable[[str], None] = lambda _: None,
) -> Serial:
    """At most `most` episodes; a short story with one turn stays one episode."""
    events = await digest(adapter, text, progress)
    adaptation = await adapter.adapt(events, style, most)
    parts = cut(adaptation.parts, len(events), most)
    season = Season(
        title=adaptation.title,
        world=adaptation.world,
        characters=adaptation.characters,
        episodes=[EpisodeIdea(title=p.title, logline=p.logline) for p, _ in parts],
    )
    outlines = []
    for n, (_, numbers) in enumerate(parts):
        source = " ".join(f"{i}) {events[i - 1]}" for i in numbers)
        brief = (
            f"{episode_brief(season, n)} Retell these events of the source in this order, "
            f"and add no event of your own: {source}"
        )
        outlines.append(await adapter.plan(brief, style))
        progress(f"episode {n + 1}: {outlines[-1].title}")
    return Serial(season, outlines)


async def digest(
    adapter: Adapter, text: str, progress: Callable[[str], None] = lambda _: None
) -> list[str]:
    """The events of the whole text, retold again until they fit the season planner."""
    events: list[str] = []
    for n, passage in enumerate(passages(text), 1):
        events += await adapter.retell(passage)
        progress(f"passage {n}: {len(events)} events")
    while len(numbered(events)) > DIGEST:
        shorter = [e for p in passages("\n\n".join(events)) for e in await adapter.retell(p)]
        if len(numbered(shorter)) >= len(numbered(events)):
            break
        events = shorter
        progress(f"retold shorter: {len(events)} events")
    return events


def numbered(events: list[str]) -> str:
    return "\n".join(f"{n}. {event}" for n, event in enumerate(events, 1))


def cut(parts: list[Part], count: int, most: int) -> list[tuple[Part, range]]:
    """The episodes in order, each with the numbers of the events it retells. The model's
    boundaries are trusted only as far as they cut the events into consecutive pieces: out
    of range, repeated or backwards ones are dropped, and the last episode always runs to
    the end, taking in whatever lies beyond `most`."""
    kept: list[Part] = []
    for part in sorted(parts, key=lambda p: p.last):
        end = min(max(part.last, 1), count)
        if not kept or end > kept[-1].last:
            kept.append(part.model_copy(update={"last": end}))
    kept = kept[:most]
    kept[-1] = kept[-1].model_copy(update={"last": count})
    pieces, start = [], 1
    for part in kept:
        pieces.append((part, range(start, part.last + 1)))
        start = part.last + 1
    return pieces


def passages(text: str, size: int = PASSAGE) -> list[str]:
    """Whole paragraphs packed up to `size` characters; a longer paragraph is cut between
    sentences, and a longer sentence where it must."""
    pieces = [p for chunk in re.split(r"\n\s*\n", text) if (p := chunk.strip())]
    found: list[str] = []
    current = ""
    for piece in (s for p in pieces for s in _fitted(p, size)):
        if current and len(current) + 2 + len(piece) > size:
            found.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        found.append(current)
    return found


def _fitted(paragraph: str, size: int) -> list[str]:
    if len(paragraph) <= size:
        return [paragraph]
    found: list[str] = []
    current = ""
    for whole in re.split(r"(?<=[.!?…])\s+", paragraph):
        rest = whole
        while len(rest) > size:
            found.append(rest[:size])
            rest = rest[size:]
        if current and len(current) + 1 + len(rest) > size:
            found.append(current)
            current = rest
        else:
            current = f"{current} {rest}" if current else rest
    if current:
        found.append(current)
    return found


def read_book(path: Path) -> str:
    """The text of a book, paragraphs separated by blank lines."""
    suffix = path.suffix.lower()
    if suffix == ".fb2":
        return _fiction_book(path.read_bytes())
    if suffix == ".epub":
        return _epub(path)
    if suffix in (".txt", ".md"):
        raw = path.read_bytes()
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw.decode("cp1251")  # older Russian libraries
    raise ValueError(f"{path.name}: books are read from {', '.join(BOOKS)}")


def _fiction_book(raw: bytes) -> str:
    root = ElementTree.fromstring(raw)
    body = next((e for e in root.iter() if _local(e.tag) == "body"), None)
    if body is None:
        raise ValueError("the FictionBook has no body")
    lines = [
        text
        for e in body.iter()
        if _local(e.tag) in ("p", "v", "subtitle")
        and (text := " ".join("".join(e.itertext()).split()))
    ]
    return "\n\n".join(lines)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _epub(path: Path) -> str:
    with zipfile.ZipFile(path) as book:
        container = ElementTree.fromstring(book.read("META-INF/container.xml"))
        opf = next(e.get("full-path", "") for e in container.iter() if _local(e.tag) == "rootfile")
        package = ElementTree.fromstring(book.read(opf))
        files = {e.get("id"): e.get("href", "") for e in package.iter() if _local(e.tag) == "item"}
        order = [e.get("idref") for e in package.iter() if _local(e.tag) == "itemref"]
        folder = PurePosixPath(opf).parent
        chapters = []
        for ref in order:
            href = files.get(ref)
            if href:
                reader = _Paragraphs()
                reader.feed(book.read(str(folder / href)).decode("utf-8", errors="replace"))
                chapters.append(reader.text())
    return "\n\n".join(c for c in chapters if c)


class _Paragraphs(HTMLParser):
    BLOCKS = frozenset({"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"})

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] = []
        self._current: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in self.BLOCKS:
            self._end()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self._skip = max(self._skip - 1, 0)
        elif tag in self.BLOCKS:
            self._end()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._current.append(data)

    def _end(self) -> None:
        if line := " ".join("".join(self._current).split()):
            self._lines.append(line)
        self._current = []

    def text(self) -> str:
        self._end()
        return "\n\n".join(self._lines)
