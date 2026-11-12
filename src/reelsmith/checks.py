"""Mistakes in a script that a program can see without asking a model: an episode that
would run longer than the channel allows, plates showing words the narrator has not said
yet, people named in a line but missing from the frame, too many shots of empty rooms in a
row, camera moves that make the video model invent what lies outside the picture, and
looks the image model cannot read.

Words are compared by their first letters, so «рация» on a plate matches «рацией» in a line.
The comparison errs toward letting a plate through."""

import re
from collections.abc import Iterator
from difflib import SequenceMatcher
from itertools import groupby

from reelsmith.models import Overlay, Script, Shot, shot_seconds
from reelsmith.styles import Style

# Stems of numerals in Russian and English, cardinal and ordinal.
NUMERALS: dict[int, tuple[str, ...]] = {
    0: ("нол", "нул", "zero"),
    1: ("один", "одн", "перв", "one", "first"),
    2: ("два", "две", "двух", "втор", "two", "second"),
    3: ("три", "трех", "трет", "three", "third"),
    4: ("четыр", "четв", "four"),
    5: ("пят", "five", "fifth"),
    6: ("шест", "six"),
    7: ("сем", "седьм", "seven"),
    8: ("восем", "восьм", "eight"),
    9: ("девят", "nine", "ninth"),
    10: ("десят", "ten"),
    11: ("одиннадц", "eleven"),
    12: ("двенадц", "twelve", "twelfth"),
    13: ("тринадц", "thirteen"),
    14: ("четырнадц", "fourteen"),
    15: ("пятнадц", "fifteen"),
    16: ("шестнадц", "sixteen"),
    17: ("семнадц", "seventeen"),
    18: ("восемнадц", "eighteen"),
    19: ("девятнадц", "nineteen"),
    20: ("двадцат", "twent"),
    30: ("тридцат", "thirt"),
    40: ("сорок", "forty", "fortieth"),
    50: ("пятьдес", "пятидес", "fift"),
    60: ("шестьдес", "шестидес", "sixt"),
    70: ("семьдес", "семидес", "sevent"),
    80: ("восемьдес", "восьмидес", "eight"),
    90: ("девяност", "ninet"),
    100: ("сто", "сотн", "hundred"),
}

_CAMERA = re.compile(
    r"\b(pans?|panning|tilts?|tilting|tracks?|tracking|follows?|following|reveals?|revealing"
    r"|orbits?|orbiting|cranes?|craning|sweeps?|sweeping|whips?)\b",
    re.IGNORECASE,
)
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)  # noqa: RUF001
_HELD = re.compile(
    r"\b(?:holding|holds|carrying|carries|clutching|clutches)\b[^,;.]*", re.IGNORECASE
)
# The name a model understands and the letters each language of the channel is written in.
LANGUAGES: dict[str, tuple[str, str]] = {
    "ru": ("Russian", "а-яё"),  # noqa: RUF001
    "uk": ("Ukrainian", "а-щьюяєіїґ"),  # noqa: RUF001
    "be": ("Belarusian", "а-яёіў"),  # noqa: RUF001
    "en": ("English", "a-z"),
}
_WORD = re.compile(r"[^\W\d_]+")
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)
_VOWELS = re.compile(r"[аеёиоуыэюяaeiouy]", re.IGNORECASE)  # noqa: RUF001
# Whisper measured the narrator at 5.4 syllables a second; slower lines before a reveal
# need the margin.
PACE = 5.0
_ENUMERATOR = re.compile(r"^\s*\d+\.\s*")


def _in_another_language(script: Script, language: str) -> str:
    shots = [
        i + 1
        for i, shot in enumerate(script.shots)
        if any(foreign(text, language) for text in [shot.line, *(o.text for o in shot.overlays)])
    ]
    where = [f"shots {_list(shots)}"] if shots else []
    if foreign(script.title, language):
        where.insert(0, "the title")
    return " and ".join(where)


def bare(word: str) -> str:
    return re.sub(r"\W", "", word.lower().replace("ё", "е"))  # noqa: RUF001


def language_name(code: str) -> str:
    return LANGUAGES.get(code, (code, ""))[0]


def foreign(text: str, language: str) -> bool:
    """Most words of `text` are spelled outside the language's letters. A language not in
    LANGUAGES is never foreign."""
    letters = LANGUAGES.get(language, ("", ""))[1]
    if not letters:
        return False
    own = re.compile(f"[{letters}]", re.IGNORECASE)
    words = _WORD.findall(text)
    return 2 * sum(1 for w in words if not own.search(w)) > len(words)


def problems(script: Script, style: Style, language: str | None = None) -> list[str]:
    """Each kind of problem as one instruction to the writer. Shots are counted from 1."""
    found: list[str] = []
    if language and (wrong := _in_another_language(script, language)):
        name = language_name(language)
        found.append(
            f"Not in {name}: {wrong}. The title, every line and every plate are in {name}; "
            "only picture, motion, looks and music stay in English."
        )
    if misfit := style.misfit(script):
        found.append(misfit)
    shortest, limit = style.story.seconds
    if (runs := spoken_seconds(script)) > limit:
        found.append(
            f"Read aloud, the episode runs about {runs:.0f} s and must stay under {limit} s. "
            "Cut whole shots or words until it fits; keep the opening and the last line."
        )
    elif runs < shortest:
        found.append(
            f"Read aloud, the episode runs about {runs:.0f} s and must last at least "
            f"{shortest} s. Give the lines their full {style.story.words} words with what the "
            "viewer needs to feel the moment; do not add events the outline does not have."
        )
    found += _skeleton(script, style)
    early: dict[str, list[int]] = {}
    for i, overlay in unsaid_plates(script):
        early.setdefault(overlay.text, []).append(i + 1)
    if early:
        listed = "; ".join(f"'{text}' on shots {_list(at)}" for text, at in early.items())
        found.append(
            f"Plates shown before the narrator says their words: {listed}. A plate goes on "
            "the shot whose line says its words, and a number on it is said in that shot."
        )
    absent = [
        f"shot {i + 1} ({', '.join(missing)})"
        for i, shot in enumerate(script.shots)
        if (missing := [n for n in named(shot.line, script) if n not in shot.cast])
    ]
    if absent:
        found.append(
            f"Named in the line but missing from `cast`: {', '.join(absent)}. Whoever the line "
            "names is in the picture and in `cast`."
        )
    moves = [
        f"shot {i + 1} '{move[0]}'"
        for i, shot in enumerate(script.shots)
        if (move := _CAMERA.search(shot.motion))
    ]
    if moves:
        found.append(
            f"Camera moves that make the video model invent what is outside the picture: "
            f"{', '.join(moves)}. The camera only holds or pushes in slowly."
        )
    moving = [i + 1 for i, shot in enumerate(script.shots) if shot.moves]
    if len(moving) > (most := int(style.story.moving * len(script.shots))):
        found.append(
            f"Shots {_list(moving)} are marked as moving, and at most {most} may be. Keep "
            "`moves` true only where a body travels or falls, or something bursts, breaks, "
            "splashes or flies; a face, a gesture or talk gets a camera move instead."
        )
    if run := _empty_run(script, style.story.empty_shots):
        found.append(
            f"Shots {run[0] + 1} to {run[1] + 1} show nobody; at most "
            f"{style.story.empty_shots} shot(s) in a row go without a character in the frame."
        )
    russian = [
        i + 1
        for i, shot in enumerate(script.shots)
        if _CYRILLIC.search(shot.picture) or _CYRILLIC.search(shot.motion)
    ]
    if russian:
        found.append(f"Write `picture` and `motion` in English: shots {_list(russian)}.")
    found += [
        f"Write the look of {c.name} in English; the image model reads English."
        for c in script.characters
        if _CYRILLIC.search(c.look)
    ]
    found += [
        f"The look of {c.name} has them '{held[0].strip()}', so it is drawn into every shot "
        "they are in. A look is age, hair, face and clothes; a thing in the hands goes in the "
        "picture of the shot that shows it."
        for c in script.characters
        if (held := _HELD.search(c.look))
    ]
    return found


def spoken_words(text: str) -> list[str]:
    """The words of `text` as they sound, without digits and punctuation."""
    return [bare(w) for w in _WORD.findall(text)]


def misspoken(line: str, heard: str) -> str:
    """Words the narrator said that the line does not have, such as a stage direction read
    aloud; empty when the take is clean. Only additions count: the transcript writes numbers
    in digits and mishears a word now and then, and neither is the narrator's fault."""
    wanted, said = spoken_words(line), spoken_words(heard)
    extra: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=wanted, b=said, autojunk=False).get_opcodes():
        if tag == "insert":
            extra += said[j1:j2]
        elif tag == "replace" and j2 - j1 > i2 - i1:
            extra += said[j1 + i2 - i1 : j2]
    latin = not _LATIN.search(line) and any(_LATIN.search(w) for w in extra)
    return " ".join(extra) if len(extra) >= 2 or latin else ""


def spoken_seconds(script: Script) -> float:
    """How long the episode runs once voiced: its syllables at the narrator's pace, each
    shot held as the voice stage will hold it."""
    return sum(shot_seconds(len(_VOWELS.findall(s.line)) / PACE) for s in script.shots)


def unsaid_plates(script: Script) -> Iterator[tuple[int, Overlay]]:
    """Plates whose words the narrator has not said by their shot. A number on a plate must
    be said in the shot itself. A plate repeated from the shot before carries on as it was."""
    heard: list[str] = []
    shown: set[tuple[str, str]] = set()
    for i, shot in enumerate(script.shots):
        now = _words(shot.line)
        heard += now
        passed: set[tuple[str, str]] = set()
        for overlay in shot.overlays:
            key = (overlay.kind, overlay.text)
            if key in shown or _said(overlay.text, heard, now):
                passed.add(key)
            else:
                yield i, overlay
        shown = passed


def present(shot: Shot, script: Script) -> list[str]:
    """Who is in the frame: the cast, and anyone the line names whom the writer forgot to
    list. Without a name in the cast their look never reaches the image model."""
    return [*shot.cast, *(n for n in named(shot.line, script) if n not in shot.cast)]


def named(line: str, script: Script) -> list[str]:
    """Characters whose name appears in the line in any case form."""
    spoken = [bare(w) for w in line.split() if re.sub(r"^\W+", "", w)[:1].isupper()]
    found = []
    for character in script.characters:
        name = bare(character.name.split()[0]) if character.name.split() else ""
        stem = name[:-1] if len(name) >= 4 else name
        if stem and any(w.startswith(stem) for w in spoken):
            found.append(character.name)
    return found


def _said(text: str, heard: list[str], now: list[str]) -> bool:
    label, colon, rest = text.partition(":")
    body = _ENUMERATOR.sub("", rest if colon else label)
    words = [w for w in _words(body.replace("|", " ")) if len(w) >= 3 or w.isdigit()]
    numbers = [int(w) for w in words if w.isdigit()]
    if numbers and not any(_number_in(n, now) for n in numbers):
        return False
    return all(_number_in(int(w), heard) if w.isdigit() else _stem_in(w, heard) for w in words)


def _stem_in(word: str, heard: list[str]) -> bool:
    stem = word[: min(4, max(3, len(word) - 2))]
    return any(w.startswith(stem) for w in heard)


def _number_in(number: int, heard: list[str]) -> bool:
    if str(number) in heard:
        return True
    if number in NUMERALS:
        parts = [number]
    elif number < 100:
        parts = [number // 10 * 10, number % 10]
    else:
        return True  # spelled too many ways to check
    return all(any(w.startswith(s) for w in heard for s in NUMERALS[p]) for p in parts)


def _words(text: str) -> list[str]:
    return [w for w in (bare(t) for t in re.split(r"[\s\-\u2013\u2014]+", text)) if w]


def _skeleton(script: Script, style: Style) -> list[str]:
    """The share of events and breaths, and their order."""
    roles = [shot.role for shot in script.shots]
    found = []
    events, breaths = style.story.events, style.story.breaths
    if events is not None and breaths is not None:
        have = (roles.count("event"), roles.count("breath"))
        if have != (events, breaths):
            found.append(
                f"The episode has {have[0]} event and {have[1]} breath shots; this channel "
                f"needs exactly {events} events and {breaths} breaths."
            )
        edges = [i + 1 for i in (0, 1, len(roles) - 1) if i < len(roles) and roles[i] != "event"]
        if edges:
            found.append(
                f"Shots {_list(sorted(set(edges)))} must be events: the opening two and the last."
            )
    doubled = [i + 1 for i in range(1, len(roles)) if roles[i] == roles[i - 1] == "breath"]
    if doubled:
        found.append(
            f"Shots {_list(doubled)} are breaths right after a breath; a breath always "
            "follows an event."
        )
    return found


def _empty_run(script: Script, most: int) -> tuple[int, int] | None:
    at = 0
    for empty, group in groupby(script.shots, key=lambda shot: not shot.cast):
        size = len(list(group))
        if empty and size > most:
            return at, at + size - 1
        at += size
    return None


def _list(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)
