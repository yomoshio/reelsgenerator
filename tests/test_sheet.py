import shutil
from pathlib import Path

import pytest

from reelsmith import runtime
from reelsmith.scenes import carried
from reelsmith.sheet import Act, Change, Item, Sheet, Shot, Stand, after, compose, faults
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
