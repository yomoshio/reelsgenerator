"""From an idea, a story or a piece of a book to an episode in beats, staged.

The planner tells the story whole first: the premise, the people, the places, the beats and
the full voiceover. The editor, when there is one, fixes the language of the voiceover.
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
from reelsmith.text import BETWEEN, foreign, language_name, seconds, sentences, words

BEAT_SECONDS = (3.5, 11.0)
LONG_BEAT = 7.0
LONG_BEATS = 4
# tools/reference_check.py wants the median scene at most 7.5 s, and a beat holds half a
# second past its last word.
MEDIAN_MOST = 7.5 - BETWEEN
THREAT_BY = 2.0
RETOLD = 0.95
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
    places: list[Place] = Field(min_length=1, max_length=6)
    beats: list[str] = Field(min_length=4, max_length=16, description="One event each, in order.")
    planted: str = Field(description="The small detail shown early that the ending brings back.")
    ending: str = Field(description="The last line of the episode, a statement.")
    narration: str = Field(description="The whole voiceover, told as one story.")

    def brief(self) -> str:
        people = "\n".join(f"  - `{c.key}` {c.name}: {c.look}" for c in self.characters)
        places = "\n".join(f"  - `{p.key}` {p.name} ({p.kind}): {p.look}" for p in self.places)
        beats = "\n".join(f"  {n}. {b}" for n, b in enumerate(self.beats, 1))
        return (
            f"Title: {self.title}\nPremise: {self.premise}\nCharacters:\n{people}\n"
            f"Places:\n{places}\nBeats:\n{beats}\nPlanted detail: {self.planted}\n"
            f"Last line: {self.ending}\nNarration:\n{self.narration}"
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


async def plan(ctx: Context, style: Style, source: str, notes: str = "") -> Outline:
    """The episode told whole; planned again while its voiceover runs too long or short."""
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
    outline = await ctx.llm.json(ctx.settings.planner, system, user, Outline)
    for _ in range(ctx.settings.rewrites):
        if not (wrong := told_length(outline.narration, style)):
            break
        outline = await ctx.llm.json(
            ctx.settings.planner, system, f"{user}\n\nThe last plan was off: {wrong}", Outline
        )
    return outline


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


async def cast(ctx: Context, style: Style, ep: Episode) -> Episode:
    """Every character with the card the rig draws them from."""
    system = prompt("cast", palette=", ".join(f"{k} {v}" for k, v in style.palette.items()))
    user = "\n".join(f"`{c.key}` {c.name}: {c.look}" for c in ep.characters)
    made = await ctx.llm.json(ctx.settings.director, system, user, Cast)
    cards = {c.key: c.card for c in made.cards}
    if missing := [c.key for c in ep.characters if c.key not in cards]:
        raise ValueError(f"no card for {', '.join(missing)}")
    people = [c.model_copy(update={"card": cards[c.key]}) for c in ep.characters]
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
    outline = await edit(ctx, await plan(ctx, style, source))
    (folder / "plan.json").write_text(outline.model_dump_json(indent=1), encoding="utf-8")
    job.note("plan", model=ctx.settings.planner, note=outline.title)
    ep, left = await cut(ctx, style, outline)
    ep = await cast(ctx, style, ep)
    looks = " ".join([*(p.look for p in outline.places), *(c.look for c in outline.characters)])
    catalog = ctx.catalog(looks) if ctx.catalog else Catalog()
    ep, staging_left = await direct(ctx, style, ep, outline.narration, catalog)
    left += staging_left
    if left:
        job.note("write", note="left: " + " | ".join(left))
    (folder / "episode.json").write_text(ep.model_dump_json(indent=1), encoding="utf-8")
