from pathlib import Path

import pytest

from reelsmith.models import StageError
from reelsmith.styles import Style, Styles
from tests.fakes import REPO_STYLES, script, style

GOOD = """
[story]
brief = "b"
[look]
frame = "f"
judge = "j"
"""


def _folder(tmp_path: Path, **files: str) -> Styles:
    for name, text in files.items():
        (tmp_path / f"{name}.toml").write_text(text, encoding="utf-8")
    return Styles(tmp_path)


@pytest.mark.parametrize("name", Styles(REPO_STYLES).names())
def test_every_shipped_style_is_valid_and_fits_the_page(name: str) -> None:
    made = Styles(REPO_STYLES).get(name)

    assert made.name == name
    assert made.about
    assert made.story.shots[0] >= 3
    for kind, plate in made.overlays.items():
        assert plate.about, kind


def test_shipped_styles_are_the_ones_we_expect() -> None:
    assert Styles(REPO_STYLES).names() == [
        "noir",
        "rules-beats",
        "rules-serial",
        "serial",
        "twist",
        "twist-graphic",
        "twist-ink",
    ]


def test_the_serial_style_offers_the_plates_the_writer_needs() -> None:
    serial = Styles(REPO_STYLES).get("rules-serial")

    assert list(serial.overlays) == ["rule", "tag", "label", "alert", "card"]
    assert serial.captions.karaoke
    assert "`rule`" in serial.menu()


def test_a_style_without_overlays_tells_the_writer_to_leave_them_empty() -> None:
    assert Styles(REPO_STYLES).get("noir").menu() == "none: leave `overlays` empty"


def test_misfit_names_the_range_the_script_missed() -> None:
    assert style().misfit(script(3)) is None
    assert style().misfit(script(12)) == "The script has 12 shots; this channel needs 3 to 10."


def test_unknown_style_lists_the_ones_there_are(tmp_path: Path) -> None:
    with pytest.raises(StageError, match=r"no style named 'x'.*have: a, b"):
        _folder(tmp_path, a=GOOD, b=GOOD).get("x")


@pytest.mark.parametrize(
    "text",
    [
        GOOD + '[captions]\naccent = "not a colour"',
        GOOD + '[overlays."Bad Kind"]\nabout = "a"',
        GOOD.replace('brief = "b"', "brief = 1\nshots = [9, 6]"),
        "not toml at all [",
    ],
)
def test_a_broken_style_is_reported_with_its_name(tmp_path: Path, text: str) -> None:
    with pytest.raises(StageError, match="style 'broken' is broken"):
        _folder(tmp_path, broken=text).get("broken")


def test_defaults_fill_in_what_a_style_leaves_out(tmp_path: Path) -> None:
    made: Style = _folder(tmp_path, small=GOOD).get("small")

    assert made.story.shots == (6, 9)
    assert made.captions.font == "Montserrat ExtraBold"
    assert made.overlays == {}
