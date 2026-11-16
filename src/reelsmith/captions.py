"""Burnt-in captions: the narrator's words grouped a few at a time, as ASS karaoke where the
word being spoken lights up. Plates are drawn by the runtime, never here."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from reelsmith.styles import Style

WIDTH, HEIGHT, FPS = 1080, 1920, 30
# A narrator who sounds close and present: rumble cut, peaks evened out, a little lift.
VOICE_CHAIN = "highpass=f=70,acompressor=threshold=0.125:ratio=3:attack=5:release=120:makeup=2"
# The level short-video platforms normalise to, so a video is neither quiet nor clipped.
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    accent: bool = False


@dataclass(frozen=True, slots=True)
class Caption:
    words: tuple[Word, ...]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def shift(words: Iterable[Word], offset: float) -> list[Word]:
    return [Word(w.text, w.start + offset, w.end + offset, w.accent) for w in words]


def captions(words: Iterable[Word], *, max_words: int = 3, max_gap: float = 0.6) -> list[Caption]:
    """Groups words into short on-screen captions the way shorts are usually subtitled."""
    groups: list[list[Word]] = []
    for word in words:
        current = groups[-1] if groups else None
        if current and len(current) < max_words and word.start - current[-1].end <= max_gap:
            current.append(word)
        else:
            groups.append([word])
    return [Caption(tuple(g)) for g in groups]


def to_ass(lines: Iterable[Caption], style: Style) -> str:
    look = style.captions
    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {WIDTH}",
        f"PlayResY: {HEIGHT}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        f"Style: Caption,{style.fonts.caption},{look.size},{_colour(look.spoken)},"
        f"{_colour(look.upcoming)},{_colour(look.outline)},&H64000000,-1,1,{look.outline_px},0,2,"
        f"80,80,{look.margin_v}",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]
    for caption in lines:
        out += _karaoke(caption, style)
    return "\n".join(out) + "\n"


def _karaoke(caption: Caption, style: Style) -> list[str]:
    """One event per word: the word being spoken takes the accent colour, words already said
    the spoken colour, the rest the upcoming one; stressed words are larger."""
    look = style.captions
    words = caption.words
    events: list[str] = []
    for now, word in enumerate(words):
        until = words[now + 1].start if now + 1 < len(words) else caption.end
        parts: list[str] = []
        for i, w in enumerate(words):
            colour = look.spoken if i < now else look.accent if i == now else look.upcoming
            size = look.stress_size if w.accent else 100
            parts.append(f"{{\\1c{_tag(colour)}\\fscx{size}\\fscy{size}}}{_plain(w.text).upper()}")
        events.append(_event(word.start, until, " ".join(parts)))
    return events


def _event(start: float, end: float, text: str) -> str:
    return f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,{text}"


def _plain(text: str) -> str:
    return re.sub(r"[{}\\]", "", text)


def _colour(hex_rgb: str) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H00{b}{g}{r}".upper()


def _tag(hex_rgb: str) -> str:
    return _colour(hex_rgb) + "&"


def ass_time(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"
