"""A script in beats, the unit of the reference format. A beat is one place and one pose of
the hero, two to four lines said in a row, and graphics that come up on the narrator's
words. The series library says which places, poses, props and sounds exist; a script may
only use those.

Code checks a beat script the way `checks` checks a shot script. Each problem is one
instruction to the writer, and a script with a problem goes back to the writer."""

import re
import tomllib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, Field, ValidationError, model_validator

from reelsmith.checks import bare, foreign, language_name
from reelsmith.models import StageError
from reelsmith.styles import Style

# Measured on part 3 of the reference: inside a beat the narrator reads 5.6 syllables a
# second, so its longest beat, 61 syllables, runs 10.9 s; each beat then holds about half a
# second more for its tail and the transition. The estimate gives 86.6 s for the 86.6 s of
# its scenes.
PACE = 5.6
BETWEEN = 0.5
BEAT_SECONDS = (3.5, 11.0)
EPISODE_SECONDS = (60.0, 95.0)
LONG_BEAT = 7.0
LONG_BEATS = 4
RULES = (2, 4)
THREAT_BY = 2.0
_VOWELS = re.compile(r"[аеёиоуыэюяaeiouy]", re.IGNORECASE)
_NUMBERED = re.compile(r"^\s*(\d+)\s*[.)]")
_SPACES = re.compile("[\\s\\-\u2013\u2014]+")

Kind = Literal[
    "rule_card", "hud", "label", "status", "stamp", "diagram_step", "lens", "prop_stage", "pose"
]
Tone = Literal["neutral", "threat", "solved", "key"]


class Reveal(BaseModel):
    """A graphic that comes up as the narrator says `on_word` and stays to the end of the
    beat, or of the episode."""

    on_word: str = Field(description="A word of the beat's lines, copied exactly.")
    occurrence: int = Field(default=1, ge=1, description="Which time the word is said, from 1.")
    kind: Kind
    text: str = Field(default="", description="In the channel's language, at most four words.")
    target: str = Field(
        default="",
        description="An anchor of the location, such as 'pipe' or 'hero'; for `pose`, the pose.",
    )
    style: Tone = "neutral"
    persist: Literal["beat", "episode"] = "beat"


class Beat(BaseModel):
    location: str = Field(description="A location of the series library.")
    pose: str = Field(description="A pose of the hero from the series library.")
    lines: list[str] = Field(min_length=2, max_length=4)
    delivery: str = Field(description="How the narrator says the whole beat.")
    reveals: list[Reveal] = Field(min_length=1, max_length=5)
    sfx: list[str] = Field(
        default_factory=list, description="Sounds of the library, one per reveal, in order."
    )

    @property
    def text(self) -> str:
        return " ".join(self.lines)


class BeatScript(BaseModel):
    title: str
    part: int = Field(ge=1)
    hook: str = Field(description="The first line: a question to the viewer or a threat.")
    hud: str = Field(description="Day and time on screen, such as 'ДЕНЬ 3 · 02:41'.")
    beats: list[Beat] = Field(min_length=9, max_length=16)
    cliffhanger: str = Field(description="The question on the closing card of the next part.")
    music: str = Field(description="Genre, tempo and mood of the background drone.")


class Anchor(BaseModel):
    """A point of a location's picture, as fractions of its width and height."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    about: str = ""


class Location(BaseModel):
    about: str
    anchors: dict[str, Anchor]

    @model_validator(mode="after")
    def _has_hero(self) -> Self:
        if "hero" not in self.anchors:
            raise ValueError("every location has a `hero` anchor where the hero stands")
        return self


class Prop(BaseModel):
    """A thing drawn at the anchor of the same name that changes in steps, such as a pipe
    wrapped in one, two, then three blankets. The first stage is how it starts."""

    about: str
    stages: list[str] = Field(min_length=2)


class Library(BaseModel):
    """Everything a series may show and play, made once and reused in every episode."""

    locations: dict[str, Location] = Field(min_length=1)
    poses: dict[str, str] = Field(min_length=1)
    props: dict[str, Prop] = Field(default_factory=dict)
    sfx: dict[str, str] = Field(default_factory=dict)

    def menu(self) -> str:
        """The library as the writer reads it."""
        places = "\n".join(
            f"  - `{key}`: {place.about} Anchors: " + ", ".join(map(_anchor, place.anchors.items()))
            for key, place in self.locations.items()
        )
        poses = "\n".join(f"  - `{key}`: {about}" for key, about in self.poses.items())
        props = "\n".join(
            f"  - `{key}`: {prop.about} Stages: " + " → ".join(prop.stages)
            for key, prop in self.props.items()
        )
        sounds = "\n".join(f"  - `{key}`: {about}" for key, about in self.sfx.items())
        return (
            f"Locations:\n{places}\nPoses of the hero:\n{poses}\n"
            f"Props that change in steps:\n{props or '  none'}\nSounds:\n{sounds or '  none'}"
        )


def _anchor(named: tuple[str, Anchor]) -> str:
    name, anchor = named
    return f"`{name}`" + (f" ({anchor.about})" if anchor.about else "")


def read_library(folder: Path) -> Library:
    path = folder / "library.toml"
    if not path.exists():
        raise StageError(f"no series library at {path}")
    try:
        return Library.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise StageError(f"series library {path} is broken: {exc}") from exc


def words(text: str) -> list[str]:
    """The words of a text as they are compared: lower case, no punctuation, and the
    Russian yo spelled as ye."""
    return [w for w in (bare(t) for t in _SPACES.split(text)) if w]


def syllables(text: str) -> int:
    return len(_VOWELS.findall(text))


def beat_seconds(beat: Beat) -> float:
    """How long the beat runs read aloud, from its syllables."""
    return syllables(beat.text) / PACE


def episode_seconds(script: BeatScript) -> float:
    """How long the episode runs: its beats read aloud and the pause after each."""
    return sum(beat_seconds(b) + BETWEEN for b in script.beats)


def word_at(beat: Beat, reveal: Reveal) -> int | None:
    """Index of the reveal's word among the beat's words, or None if it is not said there
    `occurrence` times."""
    said, wanted = words(beat.text), words(reveal.on_word)
    if not wanted:
        return None
    seen = 0
    for i in range(len(said) - len(wanted) + 1):
        if said[i : i + len(wanted)] == wanted:
            seen += 1
            if seen == reveal.occurrence:
                return i
    return None


def problems(script: BeatScript, library: Library, language: str | None = None) -> list[str]:
    """Each kind of problem as one instruction to the writer. Beats are counted from 1."""
    found = [
        *_unsaid(script),
        *_language(script, language),
        *_unknown(script, library),
        *_lengths(script),
        *_long_beats(script),
        *_rules(script),
        *_hook(script),
    ]
    return [f for f in found if f]


def _unsaid(script: BeatScript) -> list[str]:
    missing = [
        f"beat {n} '{r.on_word}'" + (f" (time {r.occurrence})" if r.occurrence > 1 else "")
        for n, beat in enumerate(script.beats, 1)
        for r in beat.reveals
        if word_at(beat, r) is None
    ]
    if not missing:
        return []
    return [
        f"`on_word` not said in its beat: {', '.join(missing)}. Copy one word of the beat's "
        "`lines` exactly as written, and set `occurrence` if the word is said more than once."
    ]


def _language(script: BeatScript, language: str | None) -> list[str]:
    if not language:
        return []
    texts = {
        "the title": [script.title],
        "the hook": [script.hook],
        "the hud": [script.hud],
        "the cliffhanger": [script.cliffhanger],
    }
    for n, beat in enumerate(script.beats, 1):
        texts[f"beat {n}"] = [*beat.lines, *(r.text for r in beat.reveals if r.text)]
    wrong = [where for where, said in texts.items() if any(foreign(t, language) for t in said)]
    if not wrong:
        return []
    name = language_name(language)
    return [
        f"Not in {name}: {', '.join(wrong)}. The title, hook, hud, cliffhanger, every line and "
        f"every reveal's text are in {name}; keys of the library stay as they are."
    ]


def _unknown(script: BeatScript, library: Library) -> list[str]:
    found: list[str] = []
    for n, beat in enumerate(script.beats, 1):
        place = library.locations.get(beat.location)
        if place is None:
            found.append(f"beat {n} location '{beat.location}'")
        if beat.pose not in library.poses:
            found.append(f"beat {n} pose '{beat.pose}'")
        for r in beat.reveals:
            if r.kind == "pose":
                if r.target not in library.poses:
                    found.append(f"beat {n} pose '{r.target}'")
            elif r.kind == "prop_stage" and r.target not in library.props:
                found.append(f"beat {n} prop '{r.target}'")
            elif r.target and place is not None and r.target not in place.anchors:
                found.append(f"beat {n} anchor '{r.target}' of '{beat.location}'")
        found += [f"beat {n} sound '{key}'" for key in beat.sfx if key not in library.sfx]
        if len(beat.sfx) > len(beat.reveals):
            found.append(f"beat {n} has more sounds than reveals")
    if not found:
        return []
    return [
        f"Not in the series library: {', '.join(found)}. Use only the locations, anchors, "
        "poses, props and sounds listed; a `pose` reveal names a pose in `target`, a "
        "`prop_stage` reveal names a prop. Every sound goes with the reveal at its place."
    ]


def _lengths(script: BeatScript) -> list[str]:
    low, high = BEAT_SECONDS
    off = [
        f"beat {n} ~{s:.0f} s"
        for n, beat in enumerate(script.beats, 1)
        if not low <= (s := beat_seconds(beat)) <= high
    ]
    found = []
    if off:
        found.append(
            f"Beats of the wrong length read aloud: {', '.join(off)}. A beat runs {low:g} to "
            f"{high:g} s: split a long one in two, join a short one to its neighbour."
        )
    total = episode_seconds(script)
    low, high = EPISODE_SECONDS
    if not low <= total <= high:
        found.append(
            f"Read aloud, the episode runs about {total:.0f} s; it must run {low:g} to {high:g} s."
        )
    return found


def _long_beats(script: BeatScript) -> list[str]:
    long = [(n, b) for n, b in enumerate(script.beats, 1) if beat_seconds(b) > LONG_BEAT]
    found = []
    if len(long) < LONG_BEATS:
        found.append(
            f"Only {len(long)} beat(s) run longer than {LONG_BEAT:g} s; at least {LONG_BEATS} "
            "must, so the scenes hold long enough for the graphics to tell the story."
        )
    thin = [str(n) for n, b in long if len(b.reveals) < 2]
    if thin:
        found.append(
            f"Long beats with a single reveal: {', '.join(thin)}. A beat longer than "
            f"{LONG_BEAT:g} s brings up at least two graphics."
        )
    return found


def _rules(script: BeatScript) -> list[str]:
    cards = [r.text for b in script.beats for r in b.reveals if r.kind == "rule_card"]
    numbers = [int(m.group(1)) if (m := _NUMBERED.match(t)) else 0 for t in cards]
    low, high = RULES
    if low <= len(numbers) <= high and numbers == list(range(1, len(numbers) + 1)):
        return []
    shown = ", ".join(f"'{t}'" for t in cards) or "none"
    return [
        f"Rule cards {shown}. An episode has {low} to {high} rule cards, numbered in order "
        "from 1 without gaps or repeats, each text starting with its number: '1. ...'."
    ]


def _hook(script: BeatScript) -> list[str]:
    first = script.beats[0]
    found = []
    if words(first.lines[0]) != words(script.hook):
        found.append("The first line of beat 1 is the `hook`, word for word.")
    said = words(first.text)
    early = [
        r
        for r in first.reveals
        if r.style == "threat"
        and (at := word_at(first, r)) is not None
        and syllables(" ".join(said[:at])) / PACE <= THREAT_BY
    ]
    if not early:
        found.append(
            f"Beat 1 brings up a graphic with style 'threat' within its first {THREAT_BY:g} s, "
            "on a word of the hook: the danger is on screen before the viewer can scroll."
        )
    return found


class BeatWriter(Protocol):
    async def write_beats(
        self, idea: str, style: Style, library: Library, notes: str | None = None
    ) -> BeatScript: ...


Write = Callable[[str | None], Awaitable[BeatScript]]


async def draft(
    write: Write, library: Library, language: str | None, rewrites: int
) -> tuple[BeatScript, int, list[str]]:
    """Writes and sends back until the code finds nothing or the rewrites are spent. Gives
    the draft with the fewest problems, how many rewrites it took, and what is left."""
    script = await write(None)
    best = (script, problems(script, library, language))
    done = 0
    while best[1] and done < rewrites:
        done += 1
        script = await write(" ".join(best[1]))
        if len(found := problems(script, library, language)) <= len(best[1]):
            best = (script, found)
    return best[0], done, best[1]


# Shown to the writer as the shape of a beat: the first is taken apart from the reference,
# the second opens an episode. Their keys come from the prototype library.
EXAMPLES = [
    Beat(
        location="riser_room",
        pose="hand_on_pipe",
        lines=[
            "Марк не отвечает стуком.",
            "Любой звук по трубе так же легко выдаст, где он.",
            "Поэтому первое — тишина.",
            "Он обматывает стояк одеялами и скотчем, и теперь его квартиры нет ни для кого.",
        ],
        delivery="quiet and collected, a pause before the rule",
        reveals=[
            Reveal(on_word="выдаст", kind="status", text="слышно по стояку", target="hero",
                   style="threat"),
            Reveal(on_word="тишина", kind="rule_card", text="1. тишина", persist="episode"),
            Reveal(on_word="одеялами", kind="prop_stage", target="pipe"),
            Reveal(on_word="нет", kind="label", text="квартиры «нет»", target="pipe",
                   style="solved"),
        ],
        sfx=["pipe_knock_muffled", "card_pop", "cloth_wrap", "ui_confirm"],
    ),
    Beat(
        location="stairwell",
        pose="look_down",
        lines=[
            "Что ты сделаешь, если снизу постучат в три часа ночи?",
            "Нина стоит на площадке и слушает лестницу.",
            "Под ней пустой этаж, там никто не живёт уже год.",
        ],
        delivery="low and slow, almost a whisper",
        reveals=[
            Reveal(on_word="постучат", kind="status", text="стук снизу", target="stairs_down",
                   style="threat"),
            Reveal(on_word="ночи", kind="hud", text="ДЕНЬ 1 · 03:00"),
            Reveal(on_word="пустой", kind="label", text="этаж пустой", target="stairs_down",
                   style="key"),
        ],
        sfx=["pipe_knock", "ui_tick", "card_pop"],
    ),
]  # fmt: skip
