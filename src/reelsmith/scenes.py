"""The stage step: the code of every beat, written by the coder and checked until it draws
what the staging says.

A round is: the coder writes the scene, the runtime draws three keyframes and reports what
is wrong with them, and when it finds nothing, the vision model answers the director's
questions about the keyframes. Every fault goes back to the coder with its own code. After
`rounds` rounds the beat gets a plain scene the code writes itself, which always runs: the
place, its things in a row, the people standing, a slow push in. The episode never stops
on one bad beat."""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from reelsmith import runtime
from reelsmith.captions import WIDTH, Word
from reelsmith.jobs import Context, Job
from reelsmith.runtime import Report
from reelsmith.story import Beat, Episode, Reveal, prompt
from reelsmith.styles import Style

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


@dataclass
class Timing:
    seconds: float
    words: list[Word]


def carried(ep: Episode, n: int) -> list[Reveal]:
    """Plates kept up from earlier beats: the last rule card, and every other plate marked
    to stay for the episode."""
    kept: list[Reveal] = []
    for beat in ep.beats[:n]:
        for r in beat.reveals:
            if r.persist != "episode":
                continue
            if r.kind == "rule_card":
                kept = [k for k in kept if k.kind != "rule_card"]
            kept.append(r)
    return kept


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


def brief(ep: Episode, n: int, timing: Timing, stood: dict[str, float], note: str) -> str:
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
        f"Place `{place.key}` ({place.kind}): {place.look}",
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
    ]
    return "\n".join(p for p in parts if p)


def examples(style: Style) -> str:
    found = sorted((style.folder / "examples").glob("*.js"))[:2]
    return "\n\n".join(f"```js\n{p.read_text(encoding='utf-8').strip()}\n```" for p in found)


def fallback(beat: Beat, kind: str, stood: dict[str, float]) -> str:
    """A scene that always runs: the place, its things in a row, the cast standing apart,
    the first of them turning to the first thing on the middle word, a slow push in."""
    things = beat.staging.things if beat.staging else []
    targets = [r.target for r in beat.reveals if r.target and r.target not in beat.cast]
    names = list(dict.fromkeys([*things, *targets]))
    free = [round(0.15 + 0.7 * i / max(len(names) - 1, 1), 2) for i in range(len(names))]
    lines = [f's.place("{kind}");']
    for i, name in enumerate(names):
        x = stood.get(name, free[i] if len(names) > 1 else 0.3)
        lines.append(f"const t{i} = s.thing({json.dumps(name)}, {{ x: {x} }});")
    spots = [0.42, 0.6, 0.75, 0.3]
    for i, key in enumerate(beat.cast):
        lines.append(f"const p{i} = s.person({json.dumps(key)}, {{ x: {spots[i % 4]} }});")
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
        "coder", brief=style.director, api=API.read_text(encoding="utf-8"), examples=examples(style)
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

    best: tuple[str, Report, list[str]] | None = None
    feedback = ""
    for done in range(1, ctx.settings.rounds + 1):
        code = await ctx.llm.code(ctx.settings.coder, system, task + feedback)
        report = await draw(code)
        faults = report.faults()
        if not faults:
            faults = await look(ctx, report.pngs, beat)
        if not faults:
            return SceneResult(code, report, done, False, [])
        if report.error is None and (best is None or len(faults) < len(best[2])):
            best = (code, report, faults)
        feedback = (
            f"\n\nYour last code:\n```js\n{code}\n```\nIt has these problems. Fix them and give "
            "the whole code again:\n" + "\n".join(f"- {f}" for f in faults)
        )
    if best is not None and len(best[2]) <= 1:
        return SceneResult(best[0], best[1], ctx.settings.rounds, False, best[2])
    plain = fallback(beat, ep.place(beat.place).kind, stood)
    report = await draw(plain)
    left = (best[2] if best else []) + report.faults()
    return SceneResult(plain, report, ctx.settings.rounds, True, left)


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
    for n, beat in enumerate(ep.beats):
        name = f"beat{n + 1:02d}"
        done = scenes / f"{name}.json"
        if (scenes / f"{name}.js").is_file() and done.is_file() and str(n + 1) not in notes:
            graph = json.loads(done.read_text(encoding="utf-8"))["graph"]
            last[beat.place] = Report(True, None, graph=graph)
            continue
        result = await stage_beat(
            ctx, style, ep, n, timing=beats[n], keys=folder / "keys",
            stood=positions(last.get(beat.place)), note=notes.get(str(n + 1), ""),
        )  # fmt: skip
        last[beat.place] = result.report
        (scenes / f"{name}.js").write_text(result.code, encoding="utf-8")
        done.write_text(
            json.dumps(
                {
                    "rounds": result.rounds,
                    "fallback": result.fallback,
                    "left": result.left,
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
