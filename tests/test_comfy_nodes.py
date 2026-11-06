import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType

import pytest

NODES = Path(__file__).parent.parent / "comfy_nodes" / "reelsmith" / "__init__.py"


@pytest.fixture
def nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("reelsmith_nodes", NODES)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    styles = tmp_path / "styles"
    styles.mkdir()
    for name in ("serial", "noir"):
        (styles / f"{name}.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "STUDIO", tmp_path / "studio")
    monkeypatch.setattr(module, "STYLES", styles)
    return module


def _requests(studio: Path) -> list[dict[str, object]]:
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((studio / "inbox").glob("*.json"))
    ]


def test_every_block_is_registered_with_a_russian_name(nodes: ModuleType) -> None:
    assert set(nodes.NODE_CLASS_MAPPINGS) == set(nodes.NODE_DISPLAY_NAME_MAPPINGS)
    assert nodes.NODE_DISPLAY_NAME_MAPPINGS["ReelsmithVideo"] == "Reelsmith · Ролик"


def test_the_video_block_drops_a_request_and_never_waits(nodes: ModuleType, tmp_path: Path) -> None:
    block = nodes.ReelsmithVideo()
    animation = next(iter(nodes.ANIMATION))

    (answer,) = block.start("  Утром квартира затоплена  ", "serial", animation)

    assert "отправлена" in answer
    assert _requests(tmp_path / "studio") == [
        {
            "kind": "video",
            "story": "Утром квартира затоплена",
            "style": "serial",
            "animation": "hybrid",
            "same_faces": False,
        }
    ]
    assert not list((tmp_path / "studio" / "inbox").glob("*.part"))


def test_an_empty_story_is_refused(nodes: ModuleType) -> None:
    with pytest.raises(ValueError, match="Впишите"):
        nodes.ReelsmithVideo().start("   ", "serial", next(iter(nodes.ANIMATION)))


def test_the_style_list_comes_from_the_styles_folder(nodes: ModuleType) -> None:
    (style_input,) = nodes.ReelsmithVideo.INPUT_TYPES()["required"]["style"]

    assert style_input == ["noir", "serial"]


def test_the_series_block_cleans_the_name_and_passes_the_switch(
    nodes: ModuleType, tmp_path: Path
) -> None:
    nodes.ReelsmithSeries().start(
        "Ночью прорвало дамбу", "мой потоп!", 10, "serial", next(iter(nodes.ANIMATION)), True
    )

    (request,) = _requests(tmp_path / "studio")
    assert (request["name"], request["episodes"], request["queue"]) == ("мой-потоп-", 10, True)


def test_the_status_block_reads_what_the_worker_wrote(nodes: ModuleType, tmp_path: Path) -> None:
    assert "ещё не писал" in nodes.ReelsmithStatus().read()[0]
    (tmp_path / "studio").mkdir(exist_ok=True)
    (tmp_path / "studio" / "status.txt").write_text("id статус\n", encoding="utf-8")

    assert nodes.ReelsmithStatus().read() == ("id статус\n",)


def test_the_pause_block_sends_pause_or_resume(nodes: ModuleType, tmp_path: Path) -> None:
    nodes.ReelsmithPause().switch(True)
    nodes.ReelsmithPause().switch(False)

    assert [r["kind"] for r in _requests(tmp_path / "studio")] == ["pause", "resume"]


def test_blocks_always_run_again(nodes: ModuleType) -> None:
    assert math.isnan(nodes.ReelsmithStatus.IS_CHANGED())
