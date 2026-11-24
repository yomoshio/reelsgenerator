"""The stage step: the code of every beat, written by the coder and checked until it draws
what the staging says.

A round is: the coder writes the scene, the runtime draws three keyframes and reports what
is wrong with them, and when it finds nothing, the vision model answers the director's
questions about the keyframes. Every fault goes back to the coder with its own code. After
`rounds` rounds the beat gets a plain scene the code writes itself, which always runs: the
place, its things in a row, the people standing, a slow push in. The episode never stops
on one bad beat."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from reelsmith import runtime
from reelsmith.captions import WIDTH, Word
from reelsmith.jobs import Context, Job
from reelsmith.llm import LlmError, NoCode
from reelsmith.runtime import Report
from reelsmith.sheet import Sheet, after, compose, mend
from reelsmith.sheet import faults as sheet_faults
from reelsmith.story import Beat, Episode, Reveal, prompt
from reelsmith.styles import Style
from reelsmith.text import words

API = Path(__file__).parent.parent.parent / "runtime" / "API.md"
FIXED = [
    "Is anything floating in the air, cut off, or standing inside something else?",
    "Does the picture show what the lines say?",
]


class Answer(BaseModel):
    question: str
    yes: bool
    why: str


class Looked(BaseModel):
    answers: list[Answer]


@dataclass
class SceneResult:
    code: str
    report: Report
    rounds: int
    fallback: bool
    left: list[str]
    tries: list[dict[str, object]] = field(default_factory=list)
    sheet: Sheet | None = None


@dataclass
class Timing:
    seconds: float
    words: list[Word]


def carried(ep: Episode, n: int) -> list[Reveal]:
    """Plates kept up from earlier beats: the last rule card and the last count. A model marks
    most of its plates to stay for the episode, and eight of them then cover the stage; a
    label or a stamp belongs to the beat that says it."""
    kept: dict[str, Reveal] = {}
    for beat in ep.beats[:n]:
        for r in beat.reveals:
            if r.persist == "episode" and r.kind in ("rule_card", "count", "hud"):
                kept[r.kind] = r
    return list(kept.values())


def positions(report: Report | None) -> dict[str, float]:
    """Where each thing stood in the last keyframe of a beat, as a fraction of the width."""
    if report is None or not report.graph:
        return {}
    items = report.graph[-1]["items"]
    return {
        i["id"]: round((i["box"][0] + i["box"][2] / 2) / WIDTH, 2)
        for i in items
        if i["kind"] == "thing"
    }


CODE = (
    "Write `function scene(s) { ... }` for this beat only, with these characters, things "
    "and words, in one ```js block."
)
SHEET_ROUNDS = 3


def brief(
    ep: Episode, n: int, timing: Timing, stood: dict[str, float], note: str, *, ask: str = CODE
) -> str:
    beat = ep.beats[n]
    place = ep.place(beat.place)
    stage = beat.staging
    said = " ".join(f"{w.text}@{w.start:.1f}" for w in timing.words)
    people = "\n".join(
        f"  - `{c.key}` {c.name}: {c.look}" for c in ep.characters if c.key in beat.cast
    )
    plates = "\n".join(
        f"  - on «{r.on_word}»: {r.kind} '{r.text}'"
        + (f" pinned to {r.target}" if r.target else "")
        for r in beat.reveals
    )
    kept = ", ".join(f"{k} at x={v}" for k, v in stood.items())
    parts = [
        f'Place {place.name}, drawn by `s.place("{place.kind}")`: {place.look}',
        f"Characters in this beat:\n{people}" if people else "Nobody is in this beat.",
        f"Lines: {beat.text}",
        f"Words with the second each starts: {said}",
        f"The beat lasts {timing.seconds:.1f} s.",
        f"Staging: shot {stage.shot}. {stage.action}" if stage else "",
        f"Things on stage: {', '.join(stage.things)}" if stage else "",
        f"Devices: {'; '.join(stage.devices)}" if stage and stage.devices else "",
        f"Plates that will appear:\n{plates}",
        f"Things already standing in this place from an earlier beat: {kept}. Keep them there."
        if kept
        else "",
        f"Notes from a person who watched it: {note}" if note else "",
        ask,
    ]
    return "\n".join(p for p in parts if p)


def examples(style: Style, beat: Beat | None = None, most: int = 2) -> str:
    """The style's scenes closest to this beat: its own two and every scene kept from an
    approved video, ranked by the words their header shares with the beat's staging."""
    found = sorted((style.folder / "examples").glob("*.js"))
    if beat is not None and beat.staging is not None:
        wanted = set(words(" ".join([beat.staging.action, *beat.staging.things, beat.text])))

        def shared(path: Path) -> int:
            head = [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("//")
            ]
            return len(wanted & set(words(" ".join(head))))

        found.sort(key=shared, reverse=True)
    chosen = found[:most]
    return "\n\n".join(f"```js\n{p.read_text(encoding='utf-8').strip()}\n```" for p in chosen)


def keep(style: Style, ep: Episode, folder: Path, job_id: str, most: int = 3) -> list[Path]:
    """Copies the best scenes of an approved video into the style's examples, so the coder
    sees them next time: those drawn in the fewest rounds, never a fallback."""
    reports = []
    for n, beat in enumerate(ep.beats, 1):
        report = folder / "scenes" / f"beat{n:02d}.json"
        if report.is_file():
            raw = json.loads(report.read_text(encoding="utf-8"))
            if not raw["fallback"] and not raw["left"]:
                reports.append((raw["rounds"], n, beat))
    kept = []
    target = style.folder / "examples"
    target.mkdir(parents=True, exist_ok=True)
    for _, n, beat in sorted(reports)[:most]:
        stage = beat.staging
        head = [f"// Beat: «{beat.text}»"]
        if stage:
            head.append(
                f"// Staging: {stage.shot}; {stage.action} Things: {', '.join(stage.things)}."
            )
        code = (folder / "scenes" / f"beat{n:02d}.js").read_text(encoding="utf-8")
        out = target / f"{job_id}-beat{n:02d}.js"
        out.write_text("\n".join(head) + "\n" + code.strip() + "\n", encoding="utf-8")
        kept.append(out)
    return kept


_SPOTS = [round(0.2 + 0.05 * i, 2) for i in range(13)]  # where a person may stand, 0.2 to 0.8
_APART = 0.15  # as far from a thing or a person as it needs to be
_OFF_FLOOR = {"water", "window", "lamp"}  # these take no room on the floor


def fallback(beat: Beat, kind: str, stood: dict[str, float]) -> str:
    """A scene that always runs: the place, its things in a row, the cast standing apart,
    the first of them turning to the first thing on the middle word, a slow push in."""
    things = beat.staging.things if beat.staging else []
    targets = [r.target for r in beat.reveals if r.target and r.target not in beat.cast]
    names = list(dict.fromkeys([*things, *targets]))
    free = [round(0.15 + 0.7 * i / max(len(names) - 1, 1), 2) for i in range(len(names))]
    lines = [f's.place("{kind}");']
    xs = [stood.get(name, free[i] if len(names) > 1 else 0.3) for i, name in enumerate(names)]
    for i, name in enumerate(names):
        lines.append(f"const t{i} = s.thing({json.dumps(name)}, {{ x: {xs[i]} }});")
    taken = [x for name, x in zip(names, xs, strict=True) if name not in _OFF_FLOOR]
    for i, key in enumerate(beat.cast):
        spot = max(
            _SPOTS, key=lambda x: (min([_APART, *(abs(x - t) for t in taken)]), -abs(x - 0.5))
        )
        taken.append(spot)
        lines.append(f"const p{i} = s.person({json.dumps(key)}, {{ x: {spot} }});")
    middle = "s.seconds / 2"
    if beat.cast and names and names[0] != "water":
        lines.append(f"p0.look(t0, {{ at: {middle} }});")
    elif beat.cast:
        lines.append(f'p0.pose("look_down", {{ at: {middle} }});')
    lines.append("s.camera.push({ at: 0.3, until: s.seconds, zoom: 1.08 });")
    return "function scene(s) {\n  " + "\n  ".join(lines) + "\n}"


async def look(ctx: Context, pngs: list[Path], beat: Beat) -> list[str]:
    """The director's questions and two fixed ones asked of the keyframes; every answer that
    says the picture is wrong, as a fault for the coder. Answers are taken in order."""
    questions = [*(beat.staging.questions if beat.staging else []), *FIXED]
    user = f"Lines: {beat.text}\nAnswer these questions in this order:\n" + "\n".join(
        f"{i}. {q}" for i, q in enumerate(questions, 1)
    )
    seen = await ctx.llm.json(ctx.settings.vision, prompt("vision"), user, Looked, images=pngs)
    wrong = []
    for question, answer in zip(questions, seen.answers, strict=False):
        expected = question != FIXED[0]
        if answer.yes != expected:
            wrong.append(f"A viewer asked «{question}» and saw otherwise: {answer.why}")
    return wrong


async def stage_beat(
    ctx: Context,
    style: Style,
    ep: Episode,
    n: int,
    *,
    timing: Timing,
    keys: Path,
    stood: dict[str, float],
    note: str = "",
) -> SceneResult:
    beat = ep.beats[n]
    system = prompt(
        "coder",
        brief=style.director,
        api=API.read_text(encoding="utf-8"),
        examples=examples(style, beat),
    )
    task = brief(ep, n, timing, stood, note)
    times = [0.4, timing.seconds / 2, max(timing.seconds - 0.3, 0.5)]
    keep = carried(ep, n)

    async def draw(code: str) -> Report:
        data = runtime.scene_input(
            ep, n, code=code, words=timing.words, seconds=timing.seconds, style=style,
            settings=ctx.settings, carried=keep, keys=times, out=keys / f"beat{n + 1:02d}",
        )  # fmt: skip
        return await runtime.keys(ctx.settings, data)

    async def write(user: str) -> tuple[str, Report]:
        """A draft and how it draws. An answer without code is a failed draft like any other:
        the coder is told and tries again."""
        try:
            code = await ctx.llm.code(
                ctx.settings.coder, system, user, temperature=ctx.settings.coder_temperature
            )
        except NoCode as exc:
            return "", Report(False, str(exc))
        return code, await draw(code)

    best: tuple[str, Report, list[str]] | None = None
    tries: list[dict[str, object]] = []
    feedback = ""
    before: set[str] | None = None
    done = 0
    for done in range(1, ctx.settings.rounds + 1):
        code, report = await write(task + feedback)
        if done == 1:
            for _ in range(ctx.settings.variants - 1):
                other, drawn = await write(task)
                if len(drawn.faults()) < len(report.faults()):
                    code, report = other, drawn
            if ctx.settings.variants > 1:
                report = await draw(code)
        faults = report.faults()
        if not faults:
            faults = await look(ctx, report.pngs, beat)
        tries.append({"code": code, "faults": faults})
        if not faults:
            return SceneResult(code, report, done, False, [], tries)
        if report.error is None and (best is None or len(faults) < len(best[2])):
            best = (code, report, faults)
        # The same doubts twice running: the coder cannot answer them, and more rounds
        # would only cost time.
        doubts = {f.split(" and saw otherwise")[0] for f in faults}
        if doubts == before and report.error is None:
            break
        before = doubts
        last = f"Your last code:\n```js\n{code}\n```\nIt has these problems" if code else "Problems"
        feedback = f"\n\n{last}. Fix them and give the whole code again:\n" + "\n".join(
            f"- {f}" for f in faults
        )
    # A scene that draws, whatever a viewer still doubts in it, shows more of the beat than
    # the plain stand-in does; the stand-in is for a beat with no scene that draws at all.
    if best is not None:
        return SceneResult(best[0], best[1], done, False, best[2], tries)
    plain = fallback(beat, ep.place(beat.place).kind, stood)
    report = await draw(plain)
    left = (best[2] if best else []) + report.faults()
    return SceneResult(plain, report, done, True, left, tries)


async def sheet_beat(
    ctx: Context,
    style: Style,
    ep: Episode,
    n: int,
    *,
    timing: Timing,
    keys: Path,
    before: Sheet | None,
    note: str = "",
    props: dict[str, str] | None = None,
) -> SceneResult | None:
    """The beat staged through a sheet: the planner fills it, a program checks it and writes
    the scene from it. A sheet that cannot be staged goes back with the reasons; None after
    the last round, and the beat is then the coder's."""
    beat = ep.beats[n]
    kind = ep.place(beat.place).kind
    looks = " ".join([ep.place(beat.place).look, beat.staging.action if beat.staging else ""])
    listed = ctx.catalog(looks).things if ctx.catalog else runtime.catalog(ctx.settings).things
    known = set(listed) | set(runtime.library_index(ctx.settings))
    ask = (
        f"Things you can name: {', '.join(listed)}.\n"
        + (
            "The place as the last beat left it; start from it:\n"
            f"{before.model_dump_json(exclude_defaults=True)}\n"
            if before
            else ""
        )
        + "Fill the sheet for this beat."
    )
    task = brief(ep, n, timing, {}, note, ask=ask)
    said = [w.text for w in timing.words]
    tries: list[dict[str, object]] = []
    feedback = ""
    for done in range(1, SHEET_ROUNDS + 1):
        try:
            sheet = await ctx.llm.json(
                ctx.settings.planner, prompt("sheet"), task + feedback, Sheet
            )
        except LlmError as exc:
            tries.append({"sheet": None, "faults": [str(exc)[:300]]})
            feedback = (
                "\n\nYour last answer was not a whole sheet. Give the sheet again as JSON only, "
                "with at most six acts."
            )
            continue
        everyone = {c.key for c in ep.characters}
        sheet = mend(sheet, everyone)
        named = known | {i.name for i in sheet.things}
        wrong = sheet_faults(sheet, beat.cast, said, named, everyone)
        report = None
        if not wrong:
            drawn = await drawings(ctx, sheet, known, {} if props is None else props)
            code = compose(sheet, kind, drawn, known)
            data = runtime.scene_input(
                ep, n, code=code, words=timing.words, seconds=timing.seconds, style=style,
                settings=ctx.settings, carried=carried(ep, n),
                keys=[0.4, timing.seconds / 2, max(timing.seconds - 0.3, 0.5)],
                out=keys / f"beat{n + 1:02d}",
            )  # fmt: skip
            report = await runtime.keys(ctx.settings, data)
            if report.error and drawn:
                # A drawing that breaks the scene is not worth a round: the thing is drawn
                # plain, and the broken drawing is forgotten.
                for name in list(drawn):
                    if props is not None:
                        props[name] = ""
                data["code"] = code = compose(sheet, kind, {}, known)
                report = await runtime.keys(ctx.settings, data)
            wrong = [report.error] if report.error else []
        tries.append({"sheet": sheet.model_dump(exclude_defaults=True), "faults": wrong})
        if report is not None and not wrong:
            return SceneResult(code, report, done, False, report.problems, tries, sheet)
        feedback = (
            f"\n\nYour last sheet:\n{sheet.model_dump_json(exclude_defaults=True)}\n"
            "It cannot be staged. Mend it and give the whole sheet again:\n"
            + "\n".join(f"- {f}" for f in wrong)
        )
    # Why no sheet staged the beat is kept beside the scene the coder then writes.
    (keys.parent / "scenes").mkdir(parents=True, exist_ok=True)
    (keys.parent / "scenes" / f"beat{n + 1:02d}.sheet.json").write_text(
        json.dumps(tries, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return None


_DRAWING = re.compile(r"^\(\s*ctx[^)]*\)\s*=>\s*\{[\s\S]*\}$")


async def drawings(
    ctx: Context, sheet: Sheet, known: set[str], props: dict[str, str]
) -> dict[str, str]:
    """A drawing for every thing of the sheet that neither the runtime nor the library has,
    made once an episode by the coder and kept in `props`; an empty one means the coder's
    drawing failed and the thing stays plain."""
    for name in [i.name for i in sheet.things if i.name not in known and i.name not in props]:
        try:
            made = await ctx.llm.code(
                ctx.settings.coder, prompt("prop"), f"Draw: {name.replace('_', ' ')}"
            )
        except (NoCode, LlmError):
            made = ""
        made = made.strip().rstrip(";")
        props[name] = made if _DRAWING.match(made) and "fillText" not in made else ""
    return {i.name: props[i.name] for i in sheet.things if props.get(i.name)}


def timings(folder: Path) -> list[Timing]:
    raw = json.loads((folder / "voice" / "timing.json").read_text(encoding="utf-8"))
    return [
        Timing(b["seconds"], [Word(w["text"], w["start"], w["end"]) for w in b["words"]])
        for b in raw["beats"]
    ]


async def stage(job: Job, folder: Path, ctx: Context) -> None:
    """The stage step: scenes/beatNN.js and its report for every beat, in order, each beat
    told where the things of its place stood before. Beats already written are kept, unless
    `scenes/notes.json` holds a note for them from a person who watched the video."""
    style = ctx.styles.get(job.style)
    ep = Episode.model_validate_json((folder / "episode.json").read_text(encoding="utf-8"))
    beats = timings(folder)
    scenes = folder / "scenes"
    scenes.mkdir(exist_ok=True)
    notes_file = scenes / "notes.json"
    notes: dict[str, str] = (
        json.loads(notes_file.read_text(encoding="utf-8")) if notes_file.is_file() else {}
    )
    last: dict[str, Report] = {}
    left_as: dict[str, Sheet] = {}
    props_file = scenes / "props.json"
    props: dict[str, str] = (
        json.loads(props_file.read_text(encoding="utf-8")) if props_file.is_file() else {}
    )
    for n, beat in enumerate(ep.beats):
        name = f"beat{n + 1:02d}"
        done = scenes / f"{name}.json"
        if (scenes / f"{name}.js").is_file() and done.is_file() and str(n + 1) not in notes:
            kept = json.loads(done.read_text(encoding="utf-8"))
            last[beat.place] = Report(True, None, graph=kept["graph"])
            if kept.get("sheet"):
                left_as[beat.place] = after(Sheet.model_validate(kept["sheet"]))
            continue
        result = None
        if ctx.settings.staging == "sheet":
            result = await sheet_beat(
                ctx, style, ep, n, timing=beats[n], keys=folder / "keys",
                before=left_as.get(beat.place), note=notes.get(str(n + 1), ""), props=props,
            )  # fmt: skip
            props_file.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
        if result is None:
            result = await stage_beat(
                ctx, style, ep, n, timing=beats[n], keys=folder / "keys",
                stood=positions(last.get(beat.place)), note=notes.get(str(n + 1), ""),
            )  # fmt: skip
        last[beat.place] = result.report
        if result.sheet:
            left_as[beat.place] = after(result.sheet)
        (scenes / f"{name}.js").write_text(result.code, encoding="utf-8")
        done.write_text(
            json.dumps(
                {
                    "rounds": result.rounds,
                    "fallback": result.fallback,
                    "left": result.left,
                    "tries": result.tries,
                    "sheet": result.sheet.model_dump(exclude_defaults=True)
                    if result.sheet
                    else None,
                    "graph": result.report.graph,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        what = "fallback" if result.fallback else f"{result.rounds} round(s)"
        job.note("stage", model=ctx.settings.coder, note=f"beat {n + 1}: {what}")
    notes_file.unlink(missing_ok=True)
