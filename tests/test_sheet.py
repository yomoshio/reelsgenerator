import shutil
from pathlib import Path

import pytest

from reelsmith import runtime, scenes
from reelsmith.llm import closed
from reelsmith.scenes import carried
from reelsmith.sheet import Act, Change, Item, Sheet, Shot, Stand, after, compose, faults, mend
from reelsmith.styles import Styles
from tests.fakes import REPO, FakeLlm, context
from tests.test_scenes import _episode, _timing

KNOWN = {"table", "fireplace", "door", "bed"}
PAW = "(ctx) => { ctx.fillStyle = '#5A4630'; ctx.fillRect(-18, -30, 36, 60); }"


def _sheet() -> Sheet:
    return Sheet(
        things=[
            Item(name="table", where="left"),
            Item(name="fireplace", where="far_right", state=2),
            Item(name="monkey_paw", on="artem", hidden=True),
        ],
        people=[
            Stand(who="artem", where="centre"),
            Stand(who="lena", where="right", facing="left"),
        ],
        acts=[
            Act(who="artem", does="take", what="monkey_paw", on_word="сидит"),
            Act(who="artem", does="give", what="monkey_paw", to="lena", on_word="кровати"),
            Act(who="lena", does="throw", what="monkey_paw", to="fireplace", on_word="воду"),
            Act(who="artem", does="feel", mood="scared", on_word="воду"),
        ],
        changes=[Change(thing="fireplace", state=3, on_word="воду")],
        camera=[Shot(move="push", to="fireplace", on_word="воду")],
    )


def test_a_sheet_says_what_cannot_be_staged() -> None:
    words = ["Артём", "сидит", "на", "кровати", "и", "слушает", "воду", "внизу"]
    assert faults(_sheet(), ["artem", "lena"], words, {*KNOWN, "monkey_paw"}) == []
    bad = _sheet().model_copy(
        update={"acts": [Act(who="oleg", does="take", what="sword", on_word="самолёт")]}
    )
    said = " ".join(faults(bad, ["artem", "lena"], words, KNOWN))
    for part in ("monkey_paw", "oleg", "sword", "самолёт"):
        assert part in said


def test_the_place_after_a_beat_is_where_the_next_one_starts() -> None:
    left = after(_sheet())
    paw = next(i for i in left.things if i.name == "monkey_paw")
    fire = next(i for i in left.things if i.name == "fireplace")
    assert paw.hidden
    assert paw.on == ""
    assert fire.state == 3
    assert next(p for p in left.people if p.who == "artem").mood == "scared"
    assert left.acts == []


@pytest.mark.skipif(
    shutil.which("node") is None or not (REPO / "runtime" / "node_modules").is_dir(),
    reason="the runtime needs node and `npm ci` in runtime/",
)
async def test_the_code_of_a_sheet_draws_without_a_fault_or_a_guess(tmp_path: Path) -> None:
    ep = _episode()
    lena = ep.characters[0].model_copy(update={"key": "lena", "name": "Лена"})
    artem = ep.characters[0].model_copy(update={"key": "artem"})
    beat = ep.beats[0].model_copy(
        update={"cast": ["artem", "lena"], "lines": ["Артём сидит на кровати и слушает воду внизу"]}
    )
    ep = ep.model_copy(update={"characters": [artem, lena], "beats": [beat, *ep.beats[1:]]})
    code = compose(_sheet(), "room", {"monkey_paw": PAW}, KNOWN)
    ctx = context(tmp_path, FakeLlm(), runtime=REPO / "runtime", library=tmp_path / "lib")
    timing = _timing(ep, 0)
    data = runtime.scene_input(
        ep, 0, code=code, words=timing.words, seconds=timing.seconds,
        style=Styles(REPO / "styles").get("blackout"), settings=ctx.settings,
        carried=carried(ep, 0), keys=[0.4, 2.0, timing.seconds - 0.2], out=tmp_path / "k",
    )  # fmt: skip
    report = await runtime.keys(ctx.settings, data)
    assert report.error is None
    assert not [f for f in report.faults() if "overlap" in f or "inside each other" in f]
    last = {i["id"] for i in report.graph[-1]["items"]}
    assert "fireplace" in last
    assert "monkey_paw" not in last


@pytest.mark.skipif(
    shutil.which("node") is None or not (REPO / "runtime" / "node_modules").is_dir(),
    reason="the runtime needs node and `npm ci` in runtime/",
)
async def test_a_sheet_that_fails_goes_back_with_the_reason_and_the_next_beat_starts_from_it(
    tmp_path: Path,
) -> None:
    ep = _episode()
    key = ep.beats[0].cast[0]
    word = ep.beats[0].text.split()[1].strip(".,!?")
    good = Sheet(
        things=[Item(name="bed", where="left"), Item(name="amulet", on=key, hidden=True)],
        people=[Stand(who=key, where="right")],
        acts=[Act(who=key, does="take", what="amulet", on_word=word)],
    )
    bad = good.model_copy(update={"people": [Stand(who="nobody", where="right")]})
    llm = FakeLlm().answer("Sheet", bad, good)
    ctx = context(tmp_path, llm, staging="sheet", runtime=REPO / "runtime", library=tmp_path / "l")
    style = Styles(REPO / "styles").get("blackout")
    result = await scenes.sheet_beat(
        ctx, style, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k", before=None
    )
    assert result is not None
    assert result.rounds == 2
    assert "nobody" in llm.calls[1][3]
    assert 's.prop("amulet"' in result.code
    left = after(result.sheet)  # type: ignore[arg-type]
    llm.answer("Sheet", good)
    await scenes.sheet_beat(
        ctx, style, ep, 0, timing=_timing(ep, 0), keys=tmp_path / "k", before=left
    )
    assert f'"on":"{key}"' in llm.calls[2][3]


async def test_a_beat_no_sheet_can_stage_is_left_to_the_coder(tmp_path: Path) -> None:
    ep = _episode()
    bad = Sheet(people=[Stand(who="nobody", where="right")])
    llm = FakeLlm().answer("Sheet", bad, bad, bad)
    ctx = context(tmp_path, llm, staging="sheet", runtime=REPO / "runtime", library=tmp_path / "l")
    result = await scenes.sheet_beat(
        ctx, Styles(REPO / "styles").get("blackout"), ep, 0, timing=_timing(ep, 0),
        keys=tmp_path / "k", before=None,
    )  # fmt: skip
    assert result is None


def test_a_json_answer_left_one_bracket_short_is_closed() -> None:
    cut = '{"people": [{"who": "a", "where": "left"}], "camera": [{"move": "back", "zoom": 1.35}'
    assert Sheet.model_validate_json(closed(cut)).camera[0].zoom == 1.35
    assert closed('{"a": "x]y"}') == '{"a": "x]y"}'
    assert closed('{"a": ["b",') == '{"a": ["b"]}'


def test_small_slips_in_a_sheet_are_mended_not_refused() -> None:
    sheet = Sheet(
        things=[Item(name="window", on="heavy_rain"), Item(name="table")],
        people=[Stand(who="artem", where="left")],
        acts=[
            Act(who="artem", does="take", what="monkey_paw"),
            Act(who="artem", does="look", what="ghost"),
            Act(who="oleg", does="walk", to="table"),
        ],
        changes=[Change(thing="heavy_rain", state=1)],
        camera=[Shot(move="push", to="ghost")],
    )
    made = mend(sheet, {"artem", "lena"})
    paw = next(i for i in made.things if i.name == "monkey_paw")
    assert (paw.on, paw.hidden) == ("artem", True)
    assert next(i for i in made.things if i.name == "window").on == ""
    assert [a.does for a in made.acts] == ["take"]
    assert made.changes == []
    assert made.camera == []
    words = ["Артём", "сидит"]
    assert (
        faults(made, ["artem"], words, {"window", "table", "monkey_paw"}, {"artem", "lena"}) == []
    )
    with_lena = made.model_copy(update={"people": [*made.people, Stand(who="lena", where="right")]})
    assert (
        faults(with_lena, ["artem"], words, {"window", "table", "monkey_paw"}, {"artem", "lena"})
        == []
    )
