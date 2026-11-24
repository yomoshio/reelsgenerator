"""The sheet of a beat: who stands where, what lies where, and what each of them does on
which word, in words from closed lists. A program turns a sheet into scene code, so the
code cannot name a call the runtime lacks; the runtime keeps things from hiding each other.

`compose` writes the code, `after` says how the beat leaves the place, which is how the
next beat in that place begins, and `faults` names what in a sheet cannot be staged."""

import json
import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

Slot = Literal["far_left", "left", "centre", "right", "far_right"]
SLOTS: dict[str, float] = {
    "far_left": 0.12, "left": 0.3, "centre": 0.5, "right": 0.7, "far_right": 0.88
}  # fmt: skip
Mood = Literal["neutral", "happy", "sad", "worried", "scared", "angry", "surprised", "tired"]
Verb = Literal[
    "take", "put", "give", "throw", "drop", "walk", "sit", "stand", "look", "point", "reach",
    "knock", "enter", "feel",
]  # fmt: skip
CARRY = {"take", "put", "give", "throw", "drop"}
PLAIN = "(ctx) => { ctx.fillStyle = '#8A7A5C'; ctx.fillRect(-22, -16, 44, 32); }"


class Item(BaseModel):
    name: str = Field(description="A thing of the catalog, or one named in `props`.")
    where: Slot = "centre"
    on: str = Field(default="", description="The thing it lies on or the person who has it.")
    hidden: bool = Field(default=False, description="In a pocket: unseen until taken.")
    state: int | None = Field(default=None, description="Fire 0-3, door 0-1, water 0-3.")


class Stand(BaseModel):
    who: str = Field(description="A character key.")
    where: Slot
    facing: Literal["left", "right"] = "right"
    mood: Mood = "neutral"
    seated_on: str = Field(default="", description="A thing with a seat, if they sit.")


class Timed(BaseModel):
    on_word: str = Field(default="", description="A word of the lines; empty is the start.")
    occurrence: int = Field(default=1, ge=1)


class Act(Timed):
    who: str
    does: Verb
    what: str = Field(default="", description="The thing or person the verb is done to.")
    to: str = Field(default="", description="For put, give, throw and walk: where it ends.")
    mood: Mood | None = Field(default=None, description="For feel.")


class Change(Timed):
    thing: str
    state: int


class Shot(Timed):
    move: Literal["push", "pan", "back"]
    to: str = Field(default="", description="A thing or a person; nothing for back.")
    zoom: float = Field(default=1.25, ge=1, le=2)


class Light(Timed):
    level: float = Field(ge=0, le=1)


class Sheet(BaseModel):
    things: list[Item] = Field(default_factory=list, max_length=8)
    people: list[Stand] = Field(max_length=4)
    acts: list[Act] = Field(default_factory=list, max_length=12)
    changes: list[Change] = Field(default_factory=list, max_length=6)
    camera: list[Shot] = Field(default_factory=list, max_length=3)
    lights: list[Light] = Field(default_factory=list, max_length=3)


# What the runtime draws itself, large enough to fill a wall; a room holds three of them.
LARGE = ["fireplace", "table", "bed", "wardrobe", "shelf", "counter", "atm", "bench", "door"]
FIXTURES = [*LARGE, "window", "chair", "lamp", "railing", "pipe", "radiator", "water"]
# Names a model gives to what is no thing at all: weather, light, sound, and the plates.
_NO_THING = re.compile(
    r"rain|snow|wind|storm|fog|mist|dark|night|shadow|silence|sound|noise|voice|smoke|"
    r"^(plate|label|count|stamp|status|rule|text|caption)_|_(plate|label|stamp|card|text)$"
)


def plain(name: str) -> str | None:
    """The runtime's own thing a made-up name means (`round_table` is a table), the name
    itself when it means none, and None for what cannot stand on a stage."""
    if name in FIXTURES:
        return name
    if _NO_THING.search(name):
        return None
    parts = name.split("_")
    return next((f for f in FIXTURES if f in parts or f + "s" in parts), name)


def mend(sheet: Sheet, known_people: set[str]) -> Sheet:
    """The sheet with its small slips put right, as a person reading it would: a thing said
    to lie on something that is not there lies on the floor, a thing someone carries but
    nobody listed is in that person's pocket, a state changed on an unlisted thing and an
    act by or at nobody are dropped. What is left for `faults` is what only the writer of
    the sheet can decide."""
    people = {p.who for p in sheet.people}
    renamed = {i.name: plain(i.name) for i in sheet.things}
    sheet = _renamed(sheet, renamed)
    things: list[Item] = []
    for item in sheet.things:
        if item.name not in people and item.name not in {t.name for t in things}:
            things.append(item.model_copy())
    used = {x for a in sheet.acts for x in (a.what, a.to)} | {c.thing for c in sheet.changes}
    large = sorted((i for i in things if i.name in LARGE), key=lambda i: i.name not in used)
    things = [i for i in things if i.name not in {x.name for x in large[3:]}]
    names = {i.name for i in things}
    for item in things:
        if item.on and item.on not in names | people:
            item.on = ""
    for act in sheet.acts:
        if act.does in CARRY and act.what and act.what not in names and act.who in people:
            things.append(Item(name=act.what, on=act.who, hidden=True))
            names.add(act.what)
    here = names | people | set(SLOTS)
    acts = [
        a
        for a in sheet.acts
        if a.who in people
        and (a.does not in CARRY or a.what in names)
        and not (a.what and a.what not in here and a.does != "sit")
        and not (a.does == "give" and a.to not in people)
        and not (a.does == "feel" and a.mood is None)
    ]
    for act in acts:
        if act.to and act.to not in here:
            act.to = ""
    return sheet.model_copy(
        update={
            "things": things[:8],
            "acts": acts,
            "changes": [c for c in sheet.changes if c.thing in names],
            "camera": [c for c in sheet.camera if not c.to or c.to in names | people],
        }
    )


def _renamed(sheet: Sheet, names: dict[str, str | None]) -> Sheet:
    """The sheet with things called by their plain names, and without those that have none."""

    def new(name: str) -> str:
        return names.get(name, name) or ""

    return sheet.model_copy(
        update={
            "things": [
                i.model_copy(update={"name": new(i.name), "on": new(i.on)})
                for i in sheet.things
                if new(i.name)
            ],
            "acts": [
                a.model_copy(update={"what": new(a.what), "to": new(a.to)}) for a in sheet.acts
            ],
            "changes": [c.model_copy(update={"thing": new(c.thing)}) for c in sheet.changes],
            "camera": [c.model_copy(update={"to": new(c.to)}) for c in sheet.camera],
        }
    )


def _act_faults(act: Act, things: set[str], people: set[str]) -> list[str]:
    out: list[str] = []
    if act.who not in people:
        out.append(f"'{act.who}' does '{act.does}' but is not in `people`")
    if act.does in CARRY and act.what not in things:
        out.append(f"'{act.who}' cannot {act.does} '{act.what}': it is not in `things`")
    if act.does == "give" and act.to not in people:
        out.append(f"'{act.who}' gives '{act.what}' to '{act.to}', who is not in `people`")
    if act.does == "feel" and act.mood is None:
        out.append(f"'{act.who}' feels, but `mood` is empty")
    if act.does in {"look", "point", "reach", "knock", "walk"} and not (act.what or act.to):
        out.append(f"'{act.who}' cannot {act.does} at nothing: fill `what`")
    return out


def faults(
    sheet: Sheet,
    cast: list[str],
    words: list[str],
    known: set[str],
    everyone: set[str] | None = None,
) -> list[str]:
    """What cannot be staged as written, each said so the writer of the sheet can mend it."""
    out: list[str] = []
    things = {i.name for i in sheet.things}
    people = {p.who for p in sheet.people}
    said = {w.strip('.,!?:;«»—"').lower() for w in words}
    for name in things - known:
        out.append(f"thing '{name}' is neither in the catalog nor in the props")
    for key in people - (everyone or set(cast)):
        out.append(f"'{key}' is not a character of this episode")
    for key in set(cast) - people:
        out.append(f"'{key}' of the cast is not placed in `people`")
    for item in sheet.things:
        if item.on and item.on not in things | people:
            out.append(f"'{item.name}' is on '{item.on}', which is not in the sheet")
    timed: list[Timed] = [*sheet.acts, *sheet.changes, *sheet.camera, *sheet.lights]
    for word in {t.on_word for t in timed if t.on_word}:
        if word.strip('.,!?:;«»—"').lower() not in said:
            out.append(f"no word «{word}» in the lines")
    for act in sheet.acts:
        out.extend(_act_faults(act, things, people))
    if not (sheet.acts or sheet.changes or sheet.camera):
        out.append("nothing happens in the beat: give it acts on the narrator's words")
    for change in sheet.changes:
        if change.thing not in things:
            out.append(f"'{change.thing}' changes state but is not in `things`")
    return out


def _at(on_word: str, occurrence: int) -> str:
    if not on_word:
        return "0"
    if occurrence > 1:
        return json.dumps({"word": on_word, "n": occurrence}, ensure_ascii=False)
    return json.dumps(on_word, ensure_ascii=False)


def _var(name: str) -> str:
    return "v_" + "".join(c if c.isalnum() else "_" for c in name)


def _act_line(act: Act, ref: Callable[[str], str]) -> str:
    who, at = _var(act.who), f"at: {_at(act.on_word, act.occurrence)}"
    what, to = ref(act.what) if act.what else "", ref(act.to) if act.to else ""
    side = "left" if SLOTS.get(act.what or act.to, 1) < 0.5 else "right"
    calls = {
        "take": f"take({what}, {{ {at} }})",
        "put": f"put({what}, {{ {f'on: {to}, ' if to else ''}{at} }})",
        "give": f"give({what}, {{ to: {to}, {at} }})",
        "throw": f"throw({what}, {{ {f'to: {to}, ' if to else ''}{at} }})",
        "drop": f"drop({what}, {{ {at} }})",
        "walk": f"walk({{ to: {to or what}, {at} }})",
        "sit": f"sit({f'{what}, ' if what else ''}{{ {at} }})",
        "stand": f"stand({{ {at} }})",
        "enter": f'enter({{ from: "{side}", {at} }})',
        "feel": f"mood({json.dumps(act.mood)}, {{ {at} }})",
    }
    return f"{who}.{calls.get(act.does) or f'{act.does}({what or to}, {{ {at} }})'};"


def compose(
    sheet: Sheet, kind: str, props: dict[str, str] | None = None, known: set[str] | None = None
) -> str:
    """Scene code for a sheet. `props` are drawings for things the catalog lacks, as
    `(ctx, t) => {...}`; a thing outside `known` with no drawing is drawn as a plain parcel,
    so every sheet draws."""
    props = props or {}
    names = {i.name for i in sheet.things} | {p.who for p in sheet.people}
    lines = [f"s.place({json.dumps(kind)});"]
    for light in (x for x in sheet.lights if not x.on_word):
        lines.append(f"s.light({light.level});")

    def ref(name: str) -> str:
        if name in names:
            return _var(name)
        return str(SLOTS[name]) if name in SLOTS else json.dumps(name)

    def thing(item: Item, on: str = "") -> str:
        opts: dict[str, object] = {} if on else {"x": SLOTS[item.where]}
        if item.state is not None:
            opts["state"] = item.state
        if item.hidden:
            opts["hidden"] = True
        body = json.dumps(opts)[1:-1]
        body = ", ".join(x for x in [body, f"on: {on}" if on else ""] if x)
        draw = props.get(item.name) or (
            PLAIN if known is not None and item.name not in known else ""
        )
        if draw:
            body = ", ".join(x for x in [body, "size: 70", f"draw: {draw}"] if x)
            return f"const {_var(item.name)} = s.prop({json.dumps(item.name)}, {{ {body} }});"
        return f"const {_var(item.name)} = s.thing({json.dumps(item.name)}, {{ {body} }});"

    people = {p.who for p in sheet.people}
    for item in (i for i in sheet.things if not i.on):
        lines.append(thing(item))
    for item in (i for i in sheet.things if i.on and i.on not in people):
        lines.append(thing(item, _var(item.on)))
    for person in sheet.people:
        opts = {"x": SLOTS[person.where], "facing": person.facing, "mood": person.mood}
        lines.append(
            f"const {_var(person.who)} = s.person({json.dumps(person.who)}, {json.dumps(opts)});"
        )
        if person.seated_on in names:
            lines.append(f"{_var(person.who)}.sit({_var(person.seated_on)}, {{ at: 0 }});")
    for item in (i for i in sheet.things if i.on in people):
        lines.append(thing(item, _var(item.on)))

    lines.extend(_act_line(act, ref) for act in sheet.acts)
    for change in sheet.changes:
        at = _at(change.on_word, change.occurrence)
        lines.append(f"{_var(change.thing)}.state({change.state}, {{ at: {at} }});")
    for light in (x for x in sheet.lights if x.on_word):
        lines.append(f"s.light({light.level}, {{ at: {_at(light.on_word, light.occurrence)} }});")
    for shot in sheet.camera:
        at = _at(shot.on_word, shot.occurrence)
        if shot.move == "back" or not shot.to:
            lines.append(f"s.camera.back({{ at: {at} }});")
        elif shot.move == "push":
            lines.append(f"s.camera.push({{ to: {ref(shot.to)}, at: {at}, zoom: {shot.zoom} }});")
        else:
            lines.append(f"s.camera.pan({{ to: {ref(shot.to)}, at: {at} }});")
    return "function scene(s) {\n  " + "\n  ".join(lines) + "\n}"


def _carried(act: Act, item: Item, where: Slot | None, items: dict[str, Item]) -> bool:
    """Moves a thing as the act says; true when the act threw it out of sight."""
    if act.does == "take":
        item.on, item.hidden = act.who, False
    elif act.does == "give":
        item.on = act.to
    elif act.does == "put":
        item.on = act.to if act.to in items else ""
    else:
        item.on = ""
    if not item.on and where and act.does in {"put", "drop"}:
        item.where = where
    if act.does == "throw" and act.to in SLOTS:
        item.where = act.to  # type: ignore[assignment]
    return act.does == "throw" and act.to in items


def _moved(act: Act, person: Stand, items: dict[str, Item], people: dict[str, Stand]) -> None:
    if act.does == "walk":
        goal = act.to or act.what
        there = items.get(goal) or people.get(goal)
        person.where = goal if goal in SLOTS else there.where if there else person.where  # type: ignore[assignment]
        person.seated_on = ""
    elif act.does in {"sit", "stand"}:
        person.seated_on = act.what if act.does == "sit" else ""
    elif act.does == "feel" and act.mood:
        person.mood = act.mood


def after(sheet: Sheet) -> Sheet:
    """The same place when the beat is over: who has what, what lies where, what burns, who
    sits. The next beat in this place starts from it, so nothing jumps between beats."""
    items = {i.name: i.model_copy() for i in sheet.things}
    people = {p.who: p.model_copy() for p in sheet.people}
    for act in sheet.acts:
        item, person = items.get(act.what), people.get(act.who)
        if act.does in CARRY and item:
            item.hidden = _carried(act, item, person.where if person else None, items)
        elif person:
            _moved(act, person, items, people)
    for change in sheet.changes:
        if change.thing in items:
            items[change.thing].state = change.state
    return Sheet(things=list(items.values()), people=list(people.values()))
