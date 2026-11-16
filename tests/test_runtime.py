import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reelsmith import runtime
from reelsmith.captions import Word
from reelsmith.settings import Settings
from reelsmith.story import Card, Episode
from reelsmith.styles import Styles
from tests.fakes import DATA, REPO

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (REPO / "runtime" / "node_modules").is_dir(),
    reason="the runtime needs node and `npm ci` in runtime/",
)
STYLE = Styles(REPO / "styles").get("blackout")
CARD = {"age": "adult", "build": "average", "skin": "light", "hair": "short",
        "hair_colour": "#222222", "top": "raincoat", "top_colour": "#2E4A70",
        "bottom": "trousers", "bottom_colour": "#1C2230", "shoes_colour": "#101014"}  # fmt: skip


def _settings(tmp_path: Path) -> Settings:
    return Settings(runtime=REPO / "runtime", library=tmp_path / "library", styles=REPO / "styles")


def _episode() -> Episode:
    ep = Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))
    people = [c.model_copy(update={"card": Card(**CARD)}) for c in ep.characters]
    return ep.model_copy(update={"characters": people})


def _words(ep: Episode, n: int) -> list[Word]:
    return [Word(w, 0.2 + i * 0.4, 0.5 + i * 0.4) for i, w in enumerate(ep.beats[n].text.split())]


SCENE = """function scene(s) {
  s.place("room");
  const bed = s.thing("bed", { x: 0.3 });
  s.thing("water", { state: 1 });
  const a = s.person("artem", { x: 0.6 });
  a.sit(bed, { at: 0.5 });
}"""


async def test_keys_give_a_report_and_pngs(tmp_path: Path) -> None:
    ep = _episode()
    words = _words(ep, 0)
    data = runtime.scene_input(
        ep, 0, code=SCENE, words=words, seconds=words[-1].end + 0.35, style=STYLE,
        settings=_settings(tmp_path), keys=[0.4, 2.0], out=tmp_path / "keys" / "beat01",
    )  # fmt: skip
    report = await runtime.keys(_settings(tmp_path), data)
    assert report.error is None
    assert [p.name for p in report.pngs] == ["beat01-0.png", "beat01-1.png"]
    assert report.graph[0]["items"][0]["id"] in {"bed", "water", "artem"}


async def test_a_broken_scene_comes_back_as_an_error(tmp_path: Path) -> None:
    ep = _episode()
    words = _words(ep, 0)
    data = runtime.scene_input(
        ep, 0, code="function scene(s) { s.thing('nothing'); }", words=words, seconds=3,
        style=STYLE, settings=_settings(tmp_path), keys=[1.0], out=tmp_path / "k" / "b",
    )  # fmt: skip
    report = await runtime.keys(_settings(tmp_path), data)
    assert report.faults() == [report.error]
    assert "no thing 'nothing'" in str(report.error)


def test_frames_stream_seconds_times_fps_frames(tmp_path: Path) -> None:
    ep = _episode()
    words = _words(ep, 0)
    data = runtime.scene_input(
        ep, 0, code=SCENE, words=words, seconds=0.4, style=STYLE,
        settings=_settings(tmp_path), mode="frames",
    )  # fmt: skip
    done = subprocess.run(
        runtime.command(_settings(tmp_path)),
        input=json.dumps(data).encode(),
        capture_output=True,
        check=True,
    )
    assert len(done.stdout) == 12 * 1080 * 1920 * 4


def test_the_catalog_lists_library_things(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    (library / "carriage.svg").write_text("<svg/>")
    found = runtime.catalog(_settings(tmp_path))
    assert "carriage" in found.things
    assert "atm" in found.things
