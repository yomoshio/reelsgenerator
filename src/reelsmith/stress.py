"""Where the stress falls in each word the narrator reads.

A reader left to guess puts it wrong in one word out of a dozen, and a listener hears
nothing else. The voice service marks a text with a plus before each stressed vowel,
«зам+ок»; here the marks are trusted only where they are safe, and the project's own list
of words has the last say. The marked text goes to the reader and nowhere else: captions,
cues and whisper keep the words as written."""

import re
from pathlib import Path

from reelsmith.text import bare

MARK = "+"
_WRITTEN = re.compile(r"[^\W\d_]+")
_MARKED = re.compile(r"\+?[^\W\d_]+(?:\+[^\W\d_]+)*")
_VOWELS = re.compile(r"[аеёиоуыэюя]", re.IGNORECASE)  # noqa: RUF001


def kept(text: str, marked: str) -> str:
    """The text with the marks that can be trusted. A word the marker respelled, «все» into
    «всё», stays as written and unmarked; so does a word of one vowel, which has nowhere
    else to be stressed. A marking that lost or gained a word is not used at all."""
    words = _MARKED.findall(marked)
    if len(words) != len(_WRITTEN.findall(text)):
        return text
    stressed = iter(words)

    def one(found: re.Match[str]) -> str:
        written, word = found.group(), next(stressed)
        same = word.replace(MARK, "") == written
        return word if same and len(_VOWELS.findall(written)) > 1 else written

    return _WRITTEN.sub(one, text)


def fixes(path: Path) -> dict[str, str]:
    """The project's own stresses, one marked word a line: names and the words the marker
    gets wrong. Lines starting with # are notes."""
    if not path.is_file():
        return {}
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return {bare(line): line.lower() for line in lines if MARK in line and line[0] != "#"}


def pinned(marked: str, known: dict[str, str]) -> str:
    """The marked text with every word from the project's list stressed as the list says."""

    def one(found: re.Match[str]) -> str:
        written = found.group().replace(MARK, "")
        fix = known.get(bare(written))
        if fix is None or len(fix.replace(MARK, "")) != len(written):
            return found.group()
        out = written
        for at in reversed([i - n for n, i in enumerate(_marks(fix))]):
            out = out[:at] + MARK + out[at:]
        return out

    return _MARKED.sub(one, marked) if known else marked


def _marks(word: str) -> list[int]:
    return [i for i, letter in enumerate(word) if letter == MARK]
