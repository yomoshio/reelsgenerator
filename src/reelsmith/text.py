"""Words as the checks compare them, and how long a text runs read aloud."""

import re

# Letters each language is written in, to tell when a model slid into another language.
LANGUAGES = {
    "ru": ("Russian", "а-яё"),  # noqa: RUF001
    "uk": ("Ukrainian", "а-щьюяєіїґ"),  # noqa: RUF001
    "be": ("Belarusian", "а-яёіў"),  # noqa: RUF001
    "en": ("English", "a-z"),
}
# Measured by whisper on part 3 of the reference: inside a beat the narrator reads 5.6
# syllables a second, and each beat holds about half a second more for its tail and the
# transition.
PACE = 5.6
BETWEEN = 0.5

_SPACES = re.compile("[\\s\\-\\u2013\\u2014]+")
_WORD = re.compile(r"[^\W\d_]+")
_VOWELS = re.compile(r"[аеёиоуыэюяєіїaeiouy]", re.IGNORECASE)  # noqa: RUF001
_SENTENCE = re.compile(r"[.!?…]+")
_CUT = re.compile(r"(?<=[.!?…])\s+")


def bare(word: str) -> str:
    """A word as it is compared: lower case, no punctuation, the Russian yo spelled as ye."""
    return re.sub(r"\W", "", word.lower().replace("ё", "е"))  # noqa: RUF001


def words(text: str) -> list[str]:
    return [w for w in (bare(t) for t in _SPACES.split(text)) if w]


def syllables(text: str) -> int:
    return len(_VOWELS.findall(text))


def sentences(text: str) -> int:
    return len(_SENTENCE.findall(text))


def sentence_list(text: str) -> list[str]:
    return [s for s in (part.strip() for part in _CUT.split(text)) if s]


def alike(one: str, other: str) -> bool:
    """Two forms of one word, roughly: «сыном» and «сын», «Уайта» and «Уайт»."""
    one, other = bare(one), bare(other)
    same = 0
    for a, b in zip(one, other, strict=False):
        if a != b:
            break
        same += 1
    return same >= max(3, min(len(one), len(other)) - 2)


def within(quote: str, text: str) -> int | None:
    """Where the words of `quote` stand in a row among the words of `text`, or None."""
    wanted, said = words(quote), words(text)
    if not wanted:
        return None
    for i in range(len(said) - len(wanted) + 1):
        if said[i : i + len(wanted)] == wanted:
            return i
    return None


def seconds(text: str) -> float:
    """How long a text runs read aloud by the narrator, without pauses between beats."""
    return syllables(text) / PACE


def language_name(code: str) -> str:
    return LANGUAGES.get(code, (code, ""))[0]


def foreign(text: str, language: str) -> bool:
    """Most words of `text` are spelled outside the language's letters. A language not in
    LANGUAGES is never foreign."""
    letters = LANGUAGES.get(language, ("", ""))[1]
    if not letters:
        return False
    own = re.compile(f"[{letters}]", re.IGNORECASE)
    found = _WORD.findall(text)
    return 2 * sum(1 for w in found if not own.search(w)) > len(found)
