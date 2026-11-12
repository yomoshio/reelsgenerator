import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image, ImageDraw

from reelsmith.beats import Anchor, read_library
from reelsmith.graphics import HERO_HEIGHT

SCRIPT = Path(__file__).parent.parent / "scripts" / "make_art.py"
FLOOD = Path(__file__).parent.parent / "studio" / "series" / "flood"


@pytest.fixture(scope="module")
def art() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_art", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_anchor_is_placed_in_words_within_the_scene_band(art: ModuleType) -> None:
    assert art.where(Anchor(x=0.7, y=0.28)) == "on the right, at mid height"
    assert art.where(Anchor(x=0.2, y=0.1)) == "on the left, high up"
    assert art.where(Anchor(x=0.5, y=0.54)) == "in the middle, low, at floor level"


def test_the_location_prompt_lays_out_the_anchors_but_not_the_people(art: ModuleType) -> None:
    library = read_library(FLOOD)
    prompt = art.location_prompt(library.locations["landing"], "flat vector, dark navy")

    assert prompt.startswith("flat vector, dark navy. The fifth-floor landing")
    assert "the flat door on the right, at mid height" in prompt
    assert "Lena" not in prompt
    assert "Layout:" in prompt


def _figure_on(backdrop: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (300, 600), backdrop)
    d = ImageDraw.Draw(img)
    d.rectangle((100, 100, 200, 560), fill=(30, 40, 60))
    d.rectangle((130, 200, 170, 300), fill=backdrop)  # a shirt the colour of the wall
    return img


def test_keying_takes_the_backdrop_off_and_keeps_the_same_colour_inside(art: ModuleType) -> None:
    cut = art.keyed(_figure_on((200, 200, 200)))

    assert cut.getpixel((10, 10))[3] == 0
    assert cut.getpixel((150, 450))[3] == 255
    assert cut.getpixel((150, 250))[3] == 255


def test_a_figure_is_cropped_to_the_hero_height_with_the_feet_on_the_bottom(
    art: ModuleType,
) -> None:
    body = art.figure(_figure_on((210, 212, 215)))

    assert body.height == HERO_HEIGHT
    assert body.getchannel("A").getbbox()[3] == HERO_HEIGHT
    assert body.width < body.height


def test_an_empty_take_is_refused(art: ModuleType) -> None:
    with pytest.raises(ValueError, match="nothing left"):
        art.figure(Image.new("RGB", (100, 200), (200, 200, 200)))


def test_pick_copies_a_take_into_the_library(art: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "library.toml").write_bytes((FLOOD / "library.toml").read_bytes())
    library = read_library(tmp_path)
    (tmp_path / "art" / "locations").mkdir(parents=True)
    (tmp_path / "art" / "poses").mkdir(parents=True)
    Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / "art" / "locations" / "flat-2.png")
    Image.new("RGBA", (4, 8)).save(tmp_path / "art" / "poses" / "stand-1.png")

    art.pick(tmp_path, library, ["flat=2", "stand=1"])

    assert Image.open(tmp_path / "locations" / "flat.png").getpixel((0, 0)) == (1, 2, 3)
    assert (tmp_path / "poses" / "stand.png").exists()
    with pytest.raises(SystemExit, match="no such take"):
        art.pick(tmp_path, library, ["flat=9"])
    with pytest.raises(SystemExit, match="expected"):
        art.pick(tmp_path, library, ["kitchen=1"])
