from pathlib import Path

import pytest

from reelsmith.styles import StyleError, Styles

REPO_STYLES = Path(__file__).parent.parent / "styles"


def test_blackout_loads_with_a_full_palette_and_its_story_rules() -> None:
    style = Styles(REPO_STYLES).get("blackout")
    assert style.story.seconds == (60, 95)
    assert style.story.rules == (2, 4)
    assert {"wall", "floor", "ink", "threat", "key", "solved"} <= set(style.palette)
    assert style.folder == REPO_STYLES / "blackout"


def test_an_unknown_style_names_the_known_ones() -> None:
    with pytest.raises(StyleError, match="known: blackout"):
        Styles(REPO_STYLES).get("noir")


def test_a_style_missing_a_palette_colour_is_refused(tmp_path: Path) -> None:
    source = (REPO_STYLES / "blackout" / "style.toml").read_text(encoding="utf-8")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "style.toml").write_text(source.replace('threat = "#C8382D"\n', ""))
    with pytest.raises(StyleError, match="palette misses threat"):
        Styles(tmp_path).get("x")
