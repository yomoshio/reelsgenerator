import json
import re
import shutil
from pathlib import Path

import pytest

from reelsmith import scenes
from reelsmith.captions import Word
from reelsmith.jobs import Jobs, Source
from reelsmith.llm import NoCode
from reelsmith.story import Card, Episode, Staging
from reelsmith.styles import Styles
from tests.fakes import DATA, REPO, FakeLlm, context

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (REPO / "runtime" / "node_modules").is_dir(),
    reason="the runtime needs node and `npm ci` in runtime/",
)
STYLE = Styles(REPO / "styles").get("blackout")
CARD = Card(age="adult", build="average", skin="light", hair="short", hair_colour="#222222",
            top="raincoat", top_colour="#2E4A70", bottom="trousers", bottom_colour="#1C2230",
            shoes_colour="#101014")  # fmt: skip
YES = {"answers": [{"question": "q", "yes": True, "why": "ok"}] * 2
       + [{"question": "floating", "yes": False, "why": "nothing floats"},
          {"question": "lines", "yes": True, "why": "it does"}]}  # fmt: skip


def _episode(beats: int = 12) -> Episode:
    ep = Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))
    things = {"room": ["bed", "window", "door"], "section": [], "stairwell": ["railing"]}
    staged = []
    for beat in ep.beats[:beats]:
        kind = ep.place(beat.place).kind
        targets = [r.target for r in beat.reveals if r.target and r.target not in beat.cast]
        here = list(dict.fromkeys([*things[kind], *targets]))
        stage = Staging(shot="wide", action="They stand.", things=here, questions=["Q1?", "Q2?"])
        staged.append(beat.model_copy(update={"staging": stage}))
    people = [c.model_copy(update={"card": CARD}) for c in ep.characters]
    return ep.model_copy(update={"beats": staged, "characters": people})


def _timing(ep: Episode, n: int) -> scenes.Timing:
    words = [
        Word(w, 0.2 + i * 0.35, 0.5 + i * 0.35) for i, w in enumerate(ep.beats[n].text.split())
    ]
    return scenes.Timing(words[-1].end + 0.35, words)


def _ctx(tmp_path: Path, llm: FakeLlm, rounds: int = 3):  # type: ignore[no-untyped-def]
    return context(tmp_path, llm, rounds=rounds, runtime=REPO / "runtime", library=tmp_path / "lib")


def _good(ep: Episode, n: int) -> str:
    return scenes.fallback(ep.beats[n], ep.place(ep.beats[n].place).kind, {})


async def test_a_runtime_error_goes_back_to_the_coder(tmp_path: Path) -> None:
    ep = _episode()
    llm = FakeLlm().answer("code", "function scene(s) { s.thing('spaceship'); }", _good(ep, 0))
    llm.answer("Looked", YES)
    result = await scenes.stage_beat(
        _ctx(tmp_path, llm), STYLE, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k", stood={}
    )
    assert result.rounds == 2
    assert not result.fallback
    second = next(c for c in llm.calls if c[0] == "code" and "Your last code" in c[3])
    assert "no thing 'spaceship'" in second[3]


async def test_a_no_from_the_viewer_goes_back_too(tmp_path: Path) -> None:
    ep = _episode()
    no = {
        "answers": [
            {"question": "q", "yes": False, "why": "he is not on the bed"},
            *YES["answers"][1:],
        ]
    }
    llm = FakeLlm().answer("code", _good(ep, 0), _good(ep, 0)).answer("Looked", no, YES)
    result = await scenes.stage_beat(
        _ctx(tmp_path, llm), STYLE, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k", stood={}
    )
    assert result.rounds == 2
    retry = [c for c in llm.calls if c[0] == "code"][1][3]
    assert "he is not on the bed" in retry


async def test_after_the_last_round_the_plain_scene_is_drawn(tmp_path: Path) -> None:
    ep = _episode()
    broken = "function scene(s) { s.person('nobody'); }"
    llm = FakeLlm().answer("code", broken, broken)
    result = await scenes.stage_beat(
        _ctx(tmp_path, llm, rounds=2), STYLE, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k",
        stood={},
    )  # fmt: skip
    assert result.fallback
    assert result.report.error is None


@pytest.mark.parametrize(
    "kind", ["room", "shop", "stairwell", "section", "street", "outdoors", "custom"]
)
async def test_the_plain_scene_passes_in_every_kind_of_place(tmp_path: Path, kind: str) -> None:
    ep = _episode()
    place = ep.place(ep.beats[0].place).model_copy(update={"kind": kind})
    ep = ep.model_copy(update={"places": [place, *ep.places[1:]]})
    llm = FakeLlm().answer("code", "x", "x")
    result = await scenes.stage_beat(
        _ctx(tmp_path, llm, rounds=1), STYLE, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k",
        stood={},
    )  # fmt: skip
    assert result.fallback
    assert result.report.faults() == []


def test_carried_keeps_the_last_rule_card_and_episode_plates() -> None:
    ep = _episode()
    kept = scenes.carried(ep, len(ep.beats))
    rules = [r.text for r in kept if r.kind == "rule_card"]
    assert len(rules) == 1
    assert rules[0].startswith("3.")


async def test_the_stage_step_writes_every_beat_and_keeps_places(tmp_path: Path) -> None:
    full = _episode()
    ep = full.model_copy(update={"beats": full.beats[3:6]})
    assert {b.place for b in ep.beats} == {"stairwell"}
    llm = FakeLlm()
    for n in range(3):
        llm.answer("code", _good(ep, n)).answer("Looked", YES)
    ctx = _ctx(tmp_path, llm)
    jobs = Jobs(ctx.settings.jobs)
    job = jobs.create(Source(kind="idea", text="x"), "blackout")
    folder = jobs.folder(job)
    (folder / "episode.json").write_text(ep.model_dump_json())
    (folder / "voice").mkdir()
    timed = [_timing(ep, n) for n in range(3)]
    beats = [
        {
            "seconds": t.seconds,
            "words": [{"text": w.text, "start": w.start, "end": w.end} for w in t.words],
        }
        for t in timed
    ]
    (folder / "voice" / "timing.json").write_text(json.dumps({"beats": beats}))
    await scenes.stage(job, folder, ctx)
    assert sorted(p.name for p in (folder / "scenes").glob("*.js")) == [
        "beat01.js",
        "beat02.js",
        "beat03.js",
    ]
    second_section = [c for c in llm.calls if c[0] == "code"][2][3]
    assert (
        "Things already standing in this place" in second_section
        or ep.beats[2].place != ep.beats[1].place
    )


def test_the_closest_examples_come_first(tmp_path: Path) -> None:
    folder = tmp_path / "style"
    (folder / "examples").mkdir(parents=True)
    (folder / "examples" / "a.js").write_text(
        "// Beat: water in the stairwell\nfunction scene(s) {}"
    )
    (folder / "examples" / "b.js").write_text(
        "// Beat: the cash machine in the shop shows an error\nfunction scene(s) {}"
    )
    style = STYLE.model_copy(update={"folder": folder})
    beat = _episode().beats[0]
    assert beat.staging is not None
    shop = beat.model_copy(
        update={
            "staging": beat.staging.model_copy(
                update={"action": "Ivan walks to the cash machine in the shop", "things": ["atm"]}
            )
        }
    )
    shown = scenes.examples(style, shop, most=1)
    assert "cash machine" in shown


def test_an_approved_video_leaves_its_best_scenes_as_examples(tmp_path: Path) -> None:
    ep = _episode(beats=3)
    folder = tmp_path / "job"
    (folder / "scenes").mkdir(parents=True)
    for n, (rounds, fell) in enumerate([(2, False), (1, False), (4, True)], 1):
        (folder / "scenes" / f"beat{n:02d}.js").write_text(f"function scene(s) {{ /* {n} */ }}")
        (folder / "scenes" / f"beat{n:02d}.json").write_text(
            json.dumps({"rounds": rounds, "fallback": fell, "left": [], "graph": []})
        )
    style = STYLE.model_copy(update={"folder": tmp_path / "style"})
    kept = scenes.keep(style, ep, folder, "1116-abc", most=2)
    assert [p.name for p in kept] == ["1116-abc-beat02.js", "1116-abc-beat01.js"]
    assert kept[0].read_text().startswith("// Beat: «")


async def test_the_best_of_several_first_drafts_is_kept(tmp_path: Path) -> None:
    ep = _episode()
    broken = "function scene(s) { s.thing('spaceship'); }"
    llm = FakeLlm().answer("code", broken, _good(ep, 0)).answer("Looked", YES)
    ctx = context(
        tmp_path, llm, rounds=1, variants=2, runtime=REPO / "runtime", library=tmp_path / "lib"
    )
    result = await scenes.stage_beat(
        ctx, STYLE, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k", stood={}
    )
    assert not result.fallback
    assert result.rounds == 1


def test_the_plain_scene_stands_people_clear_of_things_and_each_other() -> None:
    ep = _episode()
    beat = next(b for b in ep.beats if len(b.cast) == 2 and b.staging and b.staging.things)
    code = scenes.fallback(beat, "stairwell", {"railing": 0.5})
    things = [float(x) for x in re.findall(r"s\.thing\([^)]*x: ([\d.]+)", code)]
    people = [float(x) for x in re.findall(r"s\.person\([^)]*x: ([\d.]+)", code)]
    assert len(people) == 2
    assert abs(people[0] - people[1]) >= 0.15
    assert all(abs(p - t) >= 0.1 for p in people for t in things)


async def test_an_answer_without_code_is_a_round_not_a_crash(tmp_path: Path) -> None:
    ep = _episode()

    class Mute(FakeLlm):
        async def code(self, *args: object, **kwargs: object) -> str:
            reply = await super().code(*args, **kwargs)  # type: ignore[arg-type]
            if not reply:
                raise NoCode("m answered without code")
            return reply

    llm = Mute().answer("code", "", _good(ep, 0)).answer("Looked", YES)
    result = await scenes.stage_beat(
        _ctx(tmp_path, llm), STYLE, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k", stood={}
    )
    assert not result.fallback
    assert result.rounds == 2
    assert "had no code" in llm.calls[1][3]
