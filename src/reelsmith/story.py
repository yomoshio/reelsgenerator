"""From an idea, a story or a piece of a book to an episode in beats, staged.

The planner tells the story whole first: the premise, whose story it is and what they want,
the people, the places, the beats and the full voiceover. Code checks that the voiceover
can be followed by ear, and a listener who gets nothing but the voiceover says what they
understood; a plan they could not follow is written again. The editor, when there is one,
fixes the language of the voiceover.
The cutter splits the voiceover into beats word for word and puts the graphics on the
narrator's words; casting turns each person's look into a card the rig draws; the director
stages every beat with the whole episode in view, so places and the things in them stay
put. Code checks each draft, and a draft with problems goes back with them."""

import re
from collections.abc import Awaitable, Callable
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import BaseModel, Field

from reelsmith.catalog import Catalog
from reelsmith.jobs import Context, Job
from reelsmith.styles import Style
from reelsmith.text import (
    BETWEEN,
    alike,
    foreign,
    language_name,
    seconds,
    sentence_list,
    sentences,
    within,
    words,
)

BEAT_SECONDS = (3.5, 11.0)
LONG_BEAT = 7.0
LONG_BEATS = 4
# tools/reference_check.py wants the median scene at most 7.5 s, and a beat holds half a
# second past its last word.
MEDIAN_MOST = 7.5 - BETWEEN
THREAT_BY = 2.0
RETOLD = 0.95
LONG_SENTENCE = 18
HERO_BY = 3
STAKES_BY = 0.4
TURN_FROM = 0.5
_NUMBERED = re.compile(r"^\s*(\d+)\s*[.)]")
_KEY = r"^[a-z][a-z0-9_]*$"
Hex = str

# --- what the models fill ---------------------------------------------------------------


class Card(BaseModel):
    """How the rig draws a person. Every value is one the rig knows how to draw."""

    age: Literal["child", "teen", "adult", "old"]
    build: Literal["slim", "average", "heavy"]
    skin: Literal["light", "medium", "dark"]
    hair: Literal["short", "long", "bun", "braids", "bald", "curly", "ponytail", "cap"]
    hair_colour: Hex = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    face: list[Literal["beard", "mustache", "glasses", "freckles"]] = Field(default_factory=list)
    top: Literal[
        "shirt", "sweater", "jacket", "coat", "raincoat", "dress", "gown", "uniform", "apron"
    ]
    top_colour: Hex = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    bottom: Literal["trousers", "skirt", "long_skirt", "shorts"]
    bottom_colour: Hex = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    shoes_colour: Hex = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    hat: Literal["none", "cap", "top_hat", "bonnet", "kerchief"] = "none"
    extras: list[Literal["necklace", "scarf", "bag", "torch"]] = Field(default_factory=list)


class Person(BaseModel):
    key: str = Field(pattern=_KEY, description="A short latin id, such as 'artem'.")
    name: str = Field(description="As the narrator calls them.")
    look: str = Field(description="In English: age, build, face, hair, clothes and colours.")
    who: str = Field(
        default="", description="Who they are in the story, two or three words: 'сын Уайта'."
    )


class Character(Person):
    card: Card | None = None


class Place(BaseModel):
    key: str = Field(pattern=_KEY, description="A short latin id, such as 'shop'.")
    name: str = Field(description="In the channel's language, such as 'Магазин'.")
    look: str = Field(description="In English: period, kind of place, light, what stands in it.")
    kind: Literal["room", "stairwell", "section", "street", "shop", "outdoors", "custom"]


class Outline(BaseModel):
    title: str
    premise: str = Field(description="What the story is about: the thought the ending leaves.")
    characters: list[Person] = Field(min_length=1, max_length=4)
    hero: str = Field(description="The key of the character whose story this is.")
    want: str = Field(description="What the hero wants or fears, one plain sentence.")
    obstacle: str = Field(description="What stands in the way or what it costs, one sentence.")
    places: list[Place] = Field(min_length=1, max_length=6)
    beats: list[str] = Field(min_length=4, max_length=16, description="One event each, in order.")
    planted: str = Field(description="The small detail shown early that the ending brings back.")
    ending: str = Field(description="The last line of the episode, a statement.")
    narration: str = Field(description="The whole voiceover, told as one story.")
    stakes_line: str = Field(
        description="The sentence of the narration, word for word, that says what is at stake."
    )
    turn_line: str = Field(
        description="The sentence of the narration, word for word, where everything changes."
    )

    def brief(self) -> str:
        people = "\n".join(f"  - `{c.key}` {c.name} ({c.who}): {c.look}" for c in self.characters)
        places = "\n".join(f"  - `{p.key}` {p.name} ({p.kind}): {p.look}" for p in self.places)
        beats = "\n".join(f"  {n}. {b}" for n, b in enumerate(self.beats, 1))
        return (
            f"Title: {self.title}\nPremise: {self.premise}\nCharacters:\n{people}\n"
            f"Places:\n{places}\nBeats:\n{beats}\nPlanted detail: {self.planted}\n"
            f"Last line: {self.ending}\nNarration:\n{self.narration}"
        )


class Heard(BaseModel):
    """What someone who heard the voiceover once, and nothing else, took from it."""

    hero: str = Field(description="Whose story it is, as the narrator calls them.")
    wants: str = Field(description="What the hero wants or fears; 'not said' if it is not said.")
    danger: str = Field(description="What threatens them; 'not said' if it is not said.")
    story: str = Field(description="What happened, in two or three sentences.")
    unclear: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Each a quote and what a listener cannot tell from what came before it.",
    )


class Edited(BaseModel):
    narration: str
    ending: str


class Reveal(BaseModel):
    """A plate that comes up as the narrator says `on_word` and stays to the end of the
    beat, or of the episode."""

    on_word: str = Field(description="One word of the beat's lines, copied exactly.")
    occurrence: int = Field(default=1, ge=1, description="Which time the word is said, from 1.")
    kind: Literal["rule_card", "hud", "label", "status", "stamp", "count"]
    text: str = Field(description="In the channel's language, at most four words.")
    target: str = Field(
        default="", description="A character key or a thing's name; empty for top plates."
    )
    tone: Literal["neutral", "threat", "solved", "key"] = "neutral"
    persist: Literal["beat", "episode"] = "beat"


class Staging(BaseModel):
    shot: Literal["wide", "medium", "close", "section", "lens", "split"]
    action: str = Field(description="In English: what moves and changes, on which words.")
    devices: list[str] = Field(default_factory=list, max_length=2)
    things: list[str] = Field(description="Every thing standing in the place in this beat.")
    questions: list[str] = Field(
        min_length=1, max_length=4, description="Yes-or-no questions a still can answer."
    )


class Beat(BaseModel):
    place: str = Field(description="A place key.")
    cast: list[str] = Field(description="Keys of the characters seen in this beat.")
    lines: list[str] = Field(min_length=1, max_length=4)
    delivery: str = Field(description="In English, how the narrator says the beat.")
    reveals: list[Reveal] = Field(min_length=1, max_length=5)
    staging: Staging | None = None

    @property
    def text(self) -> str:
        return " ".join(self.lines)


class Cut(BaseModel):
    hook: str = Field(description="The first line of beat 1: a question or a threat.")
    hud: str = Field(default="", description="Day and time on screen, such as 'ДЕНЬ 3 · 02:41'.")
    beats: list[Beat] = Field(min_length=4, max_length=20)
    cliffhanger: str = Field(default="", description="The question on the closing card.")
    music: str = Field(description="In English: genre, tempo and mood of the music.")


class Casting(BaseModel):
    key: str
    card: Card


class Cast(BaseModel):
    cards: list[Casting]


class Direction(BaseModel):
    beats: list[Staging]


class Episode(BaseModel):
    title: str
    part: int = 1
    premise: str
    hook: str
    hud: str = ""
    places: list[Place]
    characters: list[Character]
    beats: list[Beat]
    ending: str
    cliffhanger: str = ""
    music: str = ""

    def place(self, key: str) -> Place:
        return next(p for p in self.places if p.key == key)


# --- checks -------------------------------------------------------------------------------


def beat_seconds(beat: Beat) -> float:
    return seconds(beat.text)


def episode_seconds(ep: Episode) -> float:
    return sum(beat_seconds(b) + BETWEEN for b in ep.beats)


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


def told_length(narration: str, style: Style) -> str:
    """What is wrong with the length of a voiceover, or nothing when it fits."""
    runs = seconds(narration) + BETWEEN * sentences(narration) / 3
    shortest, longest = style.story.seconds
    least, most = style.story.narration_words()
    count = len(words(narration))
    if runs > longest:
        return (
            f"The narration has {count} words and runs about {runs:.0f} s read aloud; it must "
            f"stay under {longest} s, {most} words at most. Tell the same beats more tightly."
        )
    if runs < shortest:
        return (
            f"The narration has {count} words and runs only about {runs:.0f} s read aloud; it "
            f"must last at least {shortest} s, {least} to {most} words. Tell each beat fully: "
            "what the hero sees, does and feels, and what it costs them; add no new events."
        )
    return ""


def named(person: Person, told: list[str]) -> int | None:
    """The sentence that first says the person's name: the whole name, else its last word."""
    name = words(person.name)
    for wanted in (name, name[-1:]):
        for n, sentence in enumerate(told):
            said = words(sentence)
            if any(
                all(alike(a, b) for a, b in zip(said[i:], wanted, strict=False))
                for i in range(len(said) - len(wanted) + 1)
            ):
                return n
    return None


def _shared(one: str, other: str, but: str = "") -> bool:
    """Some word of `one` is said in `other`, the words of `but` aside."""
    skip = words(but)
    return any(
        alike(a, b)
        for a in words(one)
        for b in words(other)
        if not any(alike(a, s) or alike(b, s) for s in skip)
    )


def unclear(outline: Outline) -> list[str]:
    """What keeps a listener from following the voiceover, each as one instruction to the
    planner: a person named without a word on who they are, a hero who comes late, stakes
    and a turn that are not said where they belong, sentences too long to hear."""
    told = sentence_list(outline.narration)
    count = len(words(outline.narration))
    found = []
    people = {c.key: c for c in outline.characters}
    if outline.hero not in people:
        found.append(f"`hero` is '{outline.hero}'; it is one of {', '.join(sorted(people))}.")
    elif (at := named(people[outline.hero], told)) is None or at >= HERO_BY:
        found.append(
            f"The listener must know whose story it is: name {people[outline.hero].name} "
            f"within the first {HERO_BY} sentences of the narration."
        )
    bare_names = []
    for person in outline.characters:
        if (at := named(person, told)) is None:
            continue
        if not _shared(person.who, " ".join(told[at : at + 2]), but=person.name):
            bare_names.append(f"{person.name} («{told[at]}»)")
    if bare_names:
        found.append(
            f"Named without a word on who they are: {'; '.join(bare_names)}. The sentence that "
            "first names a person, or the one after it, says who they are in the words of "
            "their `who`: a son, an old friend, a neighbour."
        )
    for field, line in (("stakes_line", outline.stakes_line), ("turn_line", outline.turn_line)):
        if within(line, outline.narration) is None:
            found.append(f"`{field}` is a sentence of the narration, copied word for word.")
    stakes, turn = (within(q, outline.narration) for q in (outline.stakes_line, outline.turn_line))
    if stakes is not None and stakes > STAKES_BY * count:
        found.append(
            "The narration says what is at stake too late. Before the first half is over the "
            "listener hears in plain words what the hero wants and what it may cost them."
        )
    if turn is not None and turn < TURN_FROM * count:
        found.append(
            "The turn comes in the first half, and nothing after it changes anything. The "
            "moment everything changes belongs to the second half of the narration."
        )
    if told and words(told[-1]) != words(outline.ending):
        found.append("The last sentence of the narration is `ending`, word for word.")
    if long := [s for s in told if len(words(s)) > LONG_SENTENCE]:
        starts = "; ".join("«" + " ".join(s.split()[:5]) + "…»" for s in long)
        found.append(
            f"Sentences too long to follow by ear: {starts}. A sentence has at most "
            f"{LONG_SENTENCE} words and brings one new thing; split these."
        )
    return found


def misheard(outline: Outline, heard: Heard) -> list[str]:
    """What the listener did not get, as instructions to the planner."""
    found = []
    hero = next((c for c in outline.characters if c.key == outline.hero), None)
    if hero is not None and not _shared(f"{hero.name} {hero.who}", heard.hero):
        found.append(
            f"A listener took «{heard.hero}» for the hero; the story is {hero.name}'s. "
            "Open on them and tell every event from their side."
        )
    for field, said in (("wants or fears", heard.wants), ("is in danger of", heard.danger)):
        if "not said" in said.lower() or not said.strip():
            found.append(f"A listener could not tell what the hero {field}. Say it in plain words.")
    if heard.unclear:
        found.append(
            "A listener who heard the narration once could not follow: "
            + " | ".join(heard.unclear)
            + ". Say what is missing before it is needed, or drop the detail."
        )
    return found


def problems(
    ep: Episode, style: Style, language: str, narration: str, catalog: Catalog | None = None
) -> list[str]:
    """Each kind of problem as one instruction to the writer. Beats are counted from 1.
    With a catalog the staging is checked too."""
    found = [
        _retold(ep, narration),
        *_unknown(ep),
        *_unsaid(ep),
        _language(ep, language),
        *_lengths(ep, style),
        _rules(ep, style),
        *_hook(ep),
        *(_staging(ep, catalog) if catalog is not None else []),
    ]
    return [f for f in found if f]


def _retold(ep: Episode, narration: str) -> str:
    told = words(narration)
    said = [w for b in ep.beats for w in words(b.text)]
    matcher = SequenceMatcher(a=told, b=said, autojunk=False)
    if matcher.ratio() >= RETOLD:
        return ""
    change = ""
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag != "equal":
            lost, extra = " ".join(told[a0:a1][:12]), " ".join(said[b0:b1][:12])
            change = (
                f"«{lost}» became «{extra}»"
                if lost and extra
                else f"«{lost}» is missing"
                if lost
                else f"«{extra}» was added"
            )
            break
    return (
        "The lines must be the narration cut into beats, word for word, with nothing added, "
        f"dropped or reworded; here {change}."
    )


def _unknown(ep: Episode) -> list[str]:
    places = {p.key for p in ep.places}
    people = {c.key for c in ep.characters}
    found = []
    for n, beat in enumerate(ep.beats, 1):
        if beat.place not in places:
            found.append(f"beat {n} is in '{beat.place}', which is not a place key")
        if strangers := [k for k in beat.cast if k not in people]:
            found.append(f"beat {n} casts {', '.join(strangers)}, not character keys")
    if not found:
        return []
    return [
        "; ".join(found)
        + f". Places are {', '.join(sorted(places))}; characters {', '.join(sorted(people))}."
    ]


def _unsaid(ep: Episode) -> list[str]:
    missing = [
        f"beat {n} '{r.on_word}'" + (f" (time {r.occurrence})" if r.occurrence > 1 else "")
        for n, beat in enumerate(ep.beats, 1)
        for r in beat.reveals
        if word_at(beat, r) is None
    ]
    long = [
        f"beat {n} '{r.text}'"
        for n, beat in enumerate(ep.beats, 1)
        for r in beat.reveals
        if len(r.text.split()) > 4
    ]
    found = []
    if missing:
        found.append(
            f"`on_word` not said in its beat: {', '.join(missing)}. Copy one word of the "
            "beat's `lines` exactly as written, and set `occurrence` if it is said more than once."
        )
    if long:
        found.append(f"Plate text longer than four words: {', '.join(long)}.")
    return found


def _language(ep: Episode, language: str) -> str:
    texts = {"the title": [ep.title], "the hook": [ep.hook], "the cliffhanger": [ep.cliffhanger]}
    for n, beat in enumerate(ep.beats, 1):
        texts[f"beat {n}"] = [*beat.lines, *(r.text for r in beat.reveals)]
    wrong = [where for where, said in texts.items() if any(foreign(t, language) for t in said)]
    if not wrong:
        return ""
    name = language_name(language)
    return (
        f"Not in {name}: {', '.join(wrong)}. The title, hook, cliffhanger, every line and every "
        f"plate are in {name}; keys and staging stay in English."
    )


def _lengths(ep: Episode, style: Style) -> list[str]:
    found = []
    low, high = style.story.beats
    if not low <= len(ep.beats) <= high:
        found.append(f"The episode has {len(ep.beats)} beats; it needs {low} to {high}.")
    low_s, high_s = BEAT_SECONDS
    off = [
        f"beat {n} ~{s:.0f} s"
        for n, beat in enumerate(ep.beats, 1)
        if not low_s <= (s := beat_seconds(beat)) <= high_s
    ]
    if off:
        found.append(
            f"Beats of the wrong length read aloud: {', '.join(off)}. A beat runs {low_s:g} to "
            f"{high_s:g} s: split a long one in two, join a short one to its neighbour."
        )
    total = episode_seconds(ep)
    shortest, longest = style.story.seconds
    if not shortest <= total <= longest:
        found.append(f"Read aloud, the episode runs about {total:.0f} s; it must run "
                     f"{shortest} to {longest} s.")  # fmt: skip
    if ep.beats and (middle := median(beat_seconds(b) for b in ep.beats)) > MEDIAN_MOST:
        found.append(
            f"Half the beats run longer than {middle:.1f} s; the median beat runs at most "
            f"{MEDIAN_MOST:g} s. Split a long beat in two, keeping two or more long ones."
        )
    long = [(n, b) for n, b in enumerate(ep.beats, 1) if beat_seconds(b) > LONG_BEAT]
    if len(long) < LONG_BEATS:
        found.append(
            f"Only {len(long)} beat(s) run longer than {LONG_BEAT:g} s; at least {LONG_BEATS} "
            "must, so the scenes hold long enough for the picture to tell the story."
        )
    if thin := [str(n) for n, b in long if len(b.reveals) < 2]:
        found.append(f"Long beats with a single plate: {', '.join(thin)}. A beat longer than "
                     f"{LONG_BEAT:g} s brings up at least two.")  # fmt: skip
    return found


def _rules(ep: Episode, style: Style) -> str:
    low, high = style.story.rules
    cards = [r.text for b in ep.beats for r in b.reveals if r.kind == "rule_card"]
    if (low, high) == (0, 0):
        return "This channel has no rule cards; use other plates." if cards else ""
    numbers = [int(m.group(1)) if (m := _NUMBERED.match(t)) else 0 for t in cards]
    if low <= len(numbers) <= high and numbers == list(range(1, len(numbers) + 1)):
        return ""
    shown = ", ".join(f"'{t}'" for t in cards) or "none"
    return (
        f"Rule cards {shown}. An episode has {low} to {high} rule cards, numbered in order "
        "from 1 without gaps or repeats, each text starting with its number: '1. ...'."
    )


def _hook(ep: Episode) -> list[str]:
    first = ep.beats[0]
    found = []
    if words(first.lines[0]) != words(ep.hook):
        found.append("The first line of beat 1 is the `hook`, word for word.")
    said = words(first.text)
    early = [
        r
        for r in first.reveals
        if r.tone == "threat"
        and (at := word_at(first, r)) is not None
        and seconds(" ".join(said[:at])) <= THREAT_BY
    ]
    if not early:
        found.append(
            f"Beat 1 brings up a plate with tone 'threat' within its first {THREAT_BY:g} s, on "
            "a word of the hook: the danger is on screen before the viewer can scroll."
        )
    return found


def _staging(ep: Episode, catalog: Catalog) -> list[str]:
    found = []
    stood: dict[str, dict[str, int]] = {}
    for n, beat in enumerate(ep.beats, 1):
        stage = beat.staging
        if stage is None:
            found.append(f"beat {n} has no staging")
            continue
        if unknown := [t for t in stage.things if t not in catalog.things]:
            found.append(f"beat {n} stages unknown things {', '.join(unknown)}")
        if strange := [d for d in stage.devices if d.split(":")[0].strip() not in catalog.devices]:
            found.append(f"beat {n} uses unknown devices {', '.join(strange)}")
        people = set(beat.cast)
        for r in beat.reveals:
            if r.target and r.target not in people and r.target not in stage.things:
                found.append(f"beat {n} pins '{r.text}' to '{r.target}', which is not on stage")
        here = stood.setdefault(beat.place, {})
        if gone := [f"{t} (beat {m})" for t, m in here.items() if t not in stage.things]:
            found.append(f"beat {n} in '{beat.place}' lost {', '.join(gone)}")
        for thing in stage.things:
            here.setdefault(thing, n)
    if not found:
        return []
    return [
        "Staging: " + "; ".join(found) + ". Things come from the catalog by name, a thing that "
        "stood in a place keeps standing there in every later beat in that place, and every "
        "plate's target is a character in the beat or a thing on stage."
    ]


# --- steps ----------------------------------------------------------------------------------

_PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str, **values: object) -> str:
    """A prompt with `{name}` filled for the given names only, so JSON in it stays as it is."""
    text = (_PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


async def listen(ctx: Context, outline: Outline) -> Heard:
    """What a listener who gets the voiceover and nothing else takes from it."""
    system = prompt("listener", language=language_name(ctx.settings.language))
    return await ctx.llm.json(ctx.settings.planner, system, outline.narration, Heard)


async def plan(
    ctx: Context, style: Style, source: str, notes: str = ""
) -> tuple[Outline, Heard | None, list[str]]:
    """The episode told whole; planned again while its voiceover runs too long or short or
    cannot be followed. Gives the best plan, what a listener took from it, and what is
    left wrong. A plan of the wrong length is not played to the listener."""
    low, high = style.story.narration_words()
    system = prompt(
        "planner",
        seconds=f"{style.story.seconds[0]} to {style.story.seconds[1]}",
        brief=style.story.brief,
        language=language_name(ctx.settings.language),
        beats=f"{style.story.beats[0]} to {style.story.beats[1]}",
        words=f"{low} to {high}",
    )
    user = source if not notes else f"{source}\n\nNotes on the last plan: {notes}"

    async def judged(said: str) -> tuple[Outline, Heard | None, list[str]]:
        outline = await ctx.llm.json(ctx.settings.planner, system, said, Outline)
        if wrong := told_length(outline.narration, style):
            return outline, None, [wrong]
        if found := unclear(outline):
            return outline, None, found
        heard = await listen(ctx, outline)
        return outline, heard, misheard(outline, heard)

    best = await judged(user)
    for _ in range(ctx.settings.rewrites):
        if not best[2]:
            break
        again = await judged(f"{user}\n\nThe last plan was off: {' '.join(best[2])}")
        if len(again[2]) <= len(best[2]):
            best = again
    return best


def script(outline: Outline, heard: Heard | None, left: list[str]) -> str:
    """The plan as a page a person reads before the episode is voiced and drawn."""
    hero = next((c.name for c in outline.characters if c.key == outline.hero), outline.hero)
    return prompt(
        "script",
        title=outline.title,
        premise=outline.premise,
        hero=hero,
        want=outline.want,
        obstacle=outline.obstacle,
        people="\n".join(f"- {c.name}: {c.who}" for c in outline.characters),
        stakes=outline.stakes_line,
        turn=outline.turn_line,
        ending=outline.ending,
        narration="\n".join(sentence_list(outline.narration)),
        heard_hero=heard.hero if heard else "—",
        heard_wants=heard.wants if heard else "—",
        heard_danger=heard.danger if heard else "—",
        heard_story=heard.story if heard else "—",
        left="\n".join(f"- {p}" for p in left) or "—",
    )


async def edit(ctx: Context, outline: Outline) -> Outline:
    """The voiceover with its language fixed, when an editor is set. An edit that changes
    the length by more than a twentieth is not kept."""
    if not ctx.settings.editor:
        return outline
    system = prompt("editor", language=language_name(ctx.settings.language))
    user = f"Narration:\n{outline.narration}\n\nLast line:\n{outline.ending}"
    edited = await ctx.llm.json(ctx.settings.editor, system, user, Edited)
    before, after = len(words(outline.narration)), len(words(edited.narration))
    if abs(after - before) > before / 20:
        return outline
    return outline.model_copy(update={"narration": edited.narration, "ending": edited.ending})


async def cut(ctx: Context, style: Style, outline: Outline) -> tuple[Episode, list[str]]:
    """The voiceover in beats with plates on the words; rewritten while the code finds
    problems. Gives the best draft and what is left wrong with it."""
    system = prompt(
        "cut",
        brief=style.story.brief,
        language=language_name(ctx.settings.language),
        beats=f"{style.story.beats[0]} to {style.story.beats[1]}",
        rules=_rules_brief(style),
    )

    async def draft(notes: str) -> Episode:
        user = outline.brief() + (
            f"\n\nFix these problems of the last draft: {notes}" if notes else ""
        )
        made = await ctx.llm.json(ctx.settings.planner, system, user, Cut)
        return Episode(
            title=outline.title,
            premise=outline.premise,
            hook=made.hook,
            hud=made.hud,
            places=outline.places,
            characters=[Character(**c.model_dump()) for c in outline.characters],
            beats=made.beats,
            ending=outline.ending,
            cliffhanger=made.cliffhanger,
            music=made.music,
        )

    def check(ep: Episode) -> list[str]:
        return problems(ep, style, ctx.settings.language, outline.narration)

    return await _best(draft, check, ctx.settings.rewrites)


# What a look says in words and the card must then show, and what a card may show only if
# the look says so. The model drops spectacles and adds a scarf; the look is the truth.
_FACE = {
    "glasses": r"glasses|spectacles|pince-nez|monocle",
    "mustache": r"m(o)?ustache|whiskers",
    "beard": r"\bbeard|bearded|goatee",
    "freckles": r"freckle",
}
_EXTRAS = {
    "necklace": r"necklace|pearls|beads|pendant",
    "scarf": r"scarf|shawl|muffler",
    "bag": r"\bbag\b|satchel|briefcase|backpack|handbag",
    "torch": r"torch|flashlight|lantern",
}
_HATS = {
    "top_hat": r"top hat|bowler|\bhat\b",
    "bonnet": r"bonnet",
    "kerchief": r"kerchief|headscarf",
    "cap": r"\bcap\b|beret",
}


def faithful(card: Card, look: str) -> Card:
    """The card with what the look names put in and what the look does not name taken off:
    face hair and spectacles, the things worn, a hat, a bald head."""
    said = look.lower()
    face = [name for name, words in _FACE.items() if re.search(words, said)]
    extras = [name for name, words in _EXTRAS.items() if re.search(words, said)]
    hat = next((name for name, words in _HATS.items() if re.search(words, said)), "none")
    update: dict[str, object] = {"face": face, "extras": extras, "hat": hat}
    if re.search(r"\bbald\b", said):
        update["hair"] = "bald"
    return card.model_copy(update=update)


PLAIN_CARD = Card(
    age="adult", build="average", skin="light", hair="short", hair_colour="#2A2C33",
    top="jacket", top_colour="#4A5160", bottom="trousers", bottom_colour="#2B2F3A",
    shoes_colour="#15171C",
)  # fmt: skip


async def cast(ctx: Context, style: Style, ep: Episode) -> Episode:
    """Every character with the card the rig draws them from."""
    system = prompt("cast", palette=", ".join(f"{k} {v}" for k, v in style.palette.items()))
    user = "\n".join(f"`{c.key}` {c.name}: {c.look}" for c in ep.characters)
    made = await ctx.llm.json(ctx.settings.director, system, user, Cast)
    cards = {c.key: c.card for c in made.cards}
    # The model renames keys now and then (`mister_white` for `mr_white`). A card for every
    # character in the order asked is taken by its place; a character still without one is
    # asked for again, and then drawn plain rather than failing the whole story.
    if len(made.cards) == len(ep.characters) and set(cards) != {c.key for c in ep.characters}:
        cards = {c.key: given.card for c, given in zip(ep.characters, made.cards, strict=True)}
    if missing := [c for c in ep.characters if c.key not in cards]:
        again = "\n".join(f"`{c.key}` {c.name}: {c.look}" for c in missing)
        more = await ctx.llm.json(ctx.settings.director, system, again, Cast)
        got = {c.key: c.card for c in more.cards}
        for c, given in zip(missing, more.cards, strict=False):
            cards[c.key] = got.get(c.key, given.card)
    for c in ep.characters:
        cards.setdefault(c.key, PLAIN_CARD)
    people = [c.model_copy(update={"card": faithful(cards[c.key], c.look)}) for c in ep.characters]
    return ep.model_copy(update={"characters": people})


async def direct(
    ctx: Context, style: Style, ep: Episode, narration: str, catalog: Catalog
) -> tuple[Episode, list[str]]:
    """Every beat staged with the whole episode in view."""
    system = prompt("director", brief=style.director, catalog=catalog.text())
    shown = ep.model_dump_json(include={"title", "places", "characters", "beats"}, indent=1)

    async def draft(notes: str) -> Episode:
        user = shown + (f"\n\nFix these problems of the last staging: {notes}" if notes else "")
        made = await ctx.llm.json(ctx.settings.director, system, user, Direction)
        staged: list[Staging | None] = [*made.beats]
        staged += [staged[-1] if staged else None] * len(ep.beats)
        beats = [
            b.model_copy(update={"staging": s}) for b, s in zip(ep.beats, staged, strict=False)
        ]
        return ep.model_copy(update={"beats": beats})

    def check(staged: Episode) -> list[str]:
        return _staging(staged, catalog)

    return await _best(draft, check, ctx.settings.rewrites)


async def _best(
    make: Callable[[str], Awaitable[Episode]], check: Callable[[Episode], list[str]], rewrites: int
) -> tuple[Episode, list[str]]:
    best = await make("")
    left = check(best)
    for _ in range(rewrites):
        if not left:
            break
        again = await make(" ".join(left))
        if len(found := check(again)) <= len(left):
            best, left = again, found
    return best, left


def _rules_brief(style: Style) -> str:
    low, high = style.story.rules
    if (low, high) == (0, 0):
        return "This channel has no rule cards: never use the kind `rule_card`."
    return (
        f"An episode has {low} to {high} rule cards, numbered from 1 in order, each said aloud "
        'by the narrator in its beat and kept up with `persist: "episode"`.'
    )


async def write(job: Job, folder: Path, ctx: Context) -> None:
    """The write stage: plan.json and episode.json in the job's folder."""
    style = ctx.styles.get(job.style)
    source = job.source.text
    outline, heard, unsolved = await plan(ctx, style, source)
    outline = await edit(ctx, outline)
    (folder / "plan.json").write_text(outline.model_dump_json(indent=1), encoding="utf-8")
    (folder / "script.md").write_text(script(outline, heard, unsolved), encoding="utf-8")
    job.note("plan", model=ctx.settings.planner, note=outline.title)
    if unsolved:
        job.note("plan", note="unclear: " + " | ".join(unsolved))
    ep, left = await cut(ctx, style, outline)
    ep = await cast(ctx, style, ep)
    looks = " ".join([*(p.look for p in outline.places), *(c.look for c in outline.characters)])
    catalog = ctx.catalog(looks) if ctx.catalog else Catalog()
    ep, staging_left = await direct(ctx, style, ep, outline.narration, catalog)
    left += staging_left
    if left:
        job.note("write", note="left: " + " | ".join(left))
    (folder / "episode.json").write_text(ep.model_dump_json(indent=1), encoding="utf-8")
