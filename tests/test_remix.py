from pathlib import Path

import pytest
from pydantic import ValidationError

from reelsmith.remix import Library, ideas_file, load, remix
from reelsmith.series import ideas

LIBRARY = Path(__file__).parent.parent / "studio" / "structures.toml"


@pytest.fixture(scope="module")
def library() -> Library:
    return load(LIBRARY)


def test_the_shipped_library_is_complete_for_every_world(library: Library) -> None:
    assert len(library.worlds()) >= 10
    assert {"space", "zombie", "survival", "catastrophe", "dystopia"} <= set(library.themes())


def test_the_same_seed_gives_the_same_ideas(library: Library) -> None:
    first = [r.idea() for r in remix(library, 5, seed=11)]

    assert first == [r.idea() for r in remix(library, 5, seed=11)]
    assert first != [r.idea() for r in remix(library, 5, seed=12)]


def test_worlds_rotate_before_any_repeats(library: Library) -> None:
    made = remix(library, len(library.worlds()), seed=3)

    assert len({r.world.text for r in made}) == len(library.worlds())


def test_every_part_fits_its_world(library: Library) -> None:
    for item in remix(library, 40, seed=5):
        assert all(part.fits(item.world.themes) for part in item.parts()[1:])
        assert item.obstacles[0] != item.obstacles[1]


def test_a_theme_keeps_only_its_worlds(library: Library) -> None:
    made = remix(library, 6, seed=1, themes=["space"])

    assert all("space" in r.world.themes for r in made)
    with pytest.raises(ValueError, match="no world for themes"):
        remix(library, 1, seed=1, themes=["western"])


def test_a_part_must_cite_a_known_source() -> None:
    with pytest.raises(ValidationError, match="unknown source"):
        Library.model_validate(
            {"sources": [], "parts": [{"kind": "world", "text": "мир", "source": "nobody"}]}
        )


def test_a_world_without_enough_obstacles_is_refused() -> None:
    source = {"id": "s", "title": "t", "why": "w"}
    parts = [
        {"kind": kind, "text": kind, "source": "s"}
        for kind in ("world", "hero", "goal", "obstacle", "ally", "twist", "ending")
    ]
    with pytest.raises(ValidationError, match="has no obstacle"):
        Library.model_validate({"sources": [source], "parts": parts})


def test_the_ideas_file_has_one_queueable_line_per_idea_and_cites_sources(
    library: Library,
) -> None:
    text = ideas_file(remix(library, 4, seed=9), library, "serial", 9)

    assert [style for _, style, _ in ideas(text.splitlines())] == ["serial"] * 4
    assert text.count("# 0") == 4
    assert all(line.count(" · ") == 2 for line in text.splitlines() if line.startswith("# 0"))
