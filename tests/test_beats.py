from pathlib import Path

import pytest
from pydantic import ValidationError

from reelsmith.beats import (
    BETWEEN,
    EXAMPLES,
    PACE,
    Beat,
    BeatScript,
    Library,
    Reveal,
    beat_seconds,
    draft,
    episode_seconds,
    problems,
    read_library,
    syllables,
    word_at,
)
from reelsmith.models import StageError

PROTO = Path(__file__).resolve().parent.parent / "studio" / "series" / "proto"
LIBRARY = read_library(PROTO)
HOOK = "Кто стучит снизу?"


def beat(seconds: float, *reveals: Reveal, first: str = "Нина слушает трубу.") -> Beat:
    """A beat that reads aloud in about `seconds`: the first line, then filler."""
    filler = round(seconds * PACE) - syllables(first)
    return Beat(
        location="riser_room",
        pose="stand",
        lines=[first, " ".join(["раз"] * filler) + "."],
        delivery="calm",
        reveals=list(reveals)
        or [Reveal(on_word="трубу", kind="label", text="труба", target="pipe")],
    )


def good() -> BeatScript:
    threat = Reveal(
        on_word="стучит", kind="status", text="стук снизу", target="floor", style="threat"
    )

    def label() -> Reveal:
        return Reveal(on_word="трубу", kind="label", text="труба", target="pipe")

    return BeatScript(
        title="Стук",
        part=1,
        hook=HOOK,
        hud="ДЕНЬ 1 · 03:00",
        beats=[
            beat(8, threat, Reveal(on_word="снизу", kind="label", text="31 этаж", target="floor"), first=HOOK),
            beat(8, Reveal(on_word="тишина", kind="rule_card", text="1. тишина", persist="episode"), label(),
                 first="Первое правило — тишина, трубу не трогать."),
            beat(8, Reveal(on_word="свет", kind="rule_card", text="2. без света", persist="episode"), label(),
                 first="Второе правило — свет не включать у трубы. Нина слушает трубу."),
            beat(8, label(), Reveal(on_word="Нина", kind="status", text="спокойна", target="hero", style="solved")),
            *(beat(6) for _ in range(6)),
        ],
        cliffhanger="КТО ПОД НАМИ?",
        music="low drone",
    )  # fmt: skip


def test_a_script_in_the_format_has_no_problems() -> None:
    script = good()

    assert problems(script, LIBRARY, "ru") == []
    assert episode_seconds(script) == pytest.approx(68 + 10 * BETWEEN, abs=1)


def test_the_example_beats_bring_their_graphics_up_on_words_they_say() -> None:
    for example in EXAMPLES:
        assert all(word_at(example, r) is not None for r in example.reveals)
        assert 3.5 <= beat_seconds(example) <= 11


def test_the_reference_beat_reads_as_long_as_it_runs_there() -> None:
    assert beat_seconds(EXAMPLES[0]) == pytest.approx(10.9, abs=0.1)


@pytest.mark.parametrize(
    ("on_word", "occurrence", "at"),
    [
        ("трубу", 1, 2),
        ("ТРУБУ!", 1, 2),
        ("раз", 3, 5),
        ("раз раз", 1, 3),
        ("трубу", 2, None),
        ("труба", 1, None),
    ],
)
def test_finds_the_word_of_a_reveal_as_written_in_the_lines(
    on_word: str, occurrence: int, at: int | None
) -> None:
    reveal = Reveal(on_word=on_word, occurrence=occurrence, kind="label", text="труба")

    assert word_at(beat(4, reveal), reveal) == at


def test_ye_and_yo_are_the_same_letter_when_words_are_compared() -> None:
    reveal = Reveal(on_word="ещё", kind="label", text="ещё")

    assert word_at(beat(4, reveal, first="Нина слушает еще раз."), reveal) == 2


def test_a_reveal_on_a_word_the_beat_never_says_goes_back() -> None:
    script = good()
    script.beats[4].reveals[0].on_word = "окно"

    (found,) = problems(script, LIBRARY, "ru")

    assert found.startswith("`on_word` not said in its beat: beat 5 'окно'.")


def test_english_text_anywhere_on_screen_goes_back() -> None:
    script = good()
    script.beats[2].reveals[1].text = "the pipe"
    script.cliffhanger = "WHO IS BELOW?"

    (found,) = problems(script, LIBRARY, "ru")

    assert found.startswith("Not in Russian: the cliffhanger, beat 3.")


def test_keys_outside_the_library_go_back_with_each_one_named() -> None:
    script = good()
    script.beats[0].location = "roof"
    script.beats[1].pose = "dance"
    script.beats[2].reveals[1].target = "window"
    script.beats[3].reveals.append(Reveal(on_word="Нина", kind="pose", target="fly"))
    script.beats[4].reveals.append(Reveal(on_word="Нина", kind="prop_stage", target="door"))
    script.beats[5].sfx = ["card_pop", "boom"]

    (found,) = problems(script, LIBRARY, "ru")

    assert (
        "beat 1 location 'roof', beat 2 pose 'dance', beat 3 anchor 'window' of 'riser_room', "
        "beat 4 pose 'fly', beat 5 prop 'door', beat 6 sound 'boom', beat 6 has more sounds than reveals."
    ) in found


def test_the_library_knows_the_prop_pose_and_sounds_of_the_example() -> None:
    (example, _) = EXAMPLES
    script = good()
    script.beats[5] = example.model_copy(
        update={"lines": ["Нина слушает трубу.", *example.lines[1:]]}
    )

    assert not [p for p in problems(script, LIBRARY, "ru") if "library" in p]


@pytest.mark.parametrize(
    ("seconds", "bad"), [(3.0, True), (3.6, False), (10.9, False), (11.6, True)]
)
def test_a_beat_runs_three_and_a_half_to_eleven_seconds(seconds: float, bad: bool) -> None:
    script = good()
    script.beats[6] = beat(seconds)

    found = [
        p for p in problems(script, LIBRARY, "ru") if p.startswith("Beats of the wrong length")
    ]

    assert bool(found) is bad
    if bad:
        assert "beat 7" in found[0]


def test_an_episode_too_long_to_read_in_ninety_five_seconds_goes_back() -> None:
    script = good()
    script.beats += [beat(10) for _ in range(3)]

    assert any(
        p.startswith("Read aloud, the episode runs about 105 s")
        for p in problems(script, LIBRARY, "ru")
    )


def test_four_long_beats_each_with_two_graphics_are_needed() -> None:
    script = good()
    script.beats[3] = beat(6)
    script.beats[2].reveals = script.beats[2].reveals[:1]

    found = problems(script, LIBRARY, "ru")

    assert any(p.startswith("Only 3 beat(s) run longer than 7 s") for p in found)
    assert any(p.startswith("Long beats with a single reveal: 3.") for p in found)


@pytest.mark.parametrize(
    "texts",
    [["1. тишина"], ["1. тишина", "3. свет"], ["1. тишина", "1. свет"], ["тишина", "2. свет"],
     ["1. а", "2. б", "3. в", "4. г", "5. д"]],
)  # fmt: skip
def test_rule_cards_are_two_to_four_numbered_in_order(texts: list[str]) -> None:
    script = good()
    for b in script.beats:
        b.reveals = [r for r in b.reveals if r.kind != "rule_card"]
    for n, text in enumerate(texts):
        script.beats[4 + n].reveals.append(Reveal(on_word="Нина", kind="rule_card", text=text))

    found = [p for p in problems(script, LIBRARY, "ru") if p.startswith("Rule cards")]

    assert len(found) == 1


def test_the_first_beat_opens_on_the_hook() -> None:
    script = good()
    script.hook = "Что под полом?"

    assert "The first line of beat 1 is the `hook`, word for word." in problems(
        script, LIBRARY, "ru"
    )


def test_the_threat_comes_up_in_the_first_two_seconds() -> None:
    script = good()
    late = Reveal(
        on_word="раз", occurrence=20, kind="status", text="опасно", target="pipe", style="threat"
    )
    script.beats[0].reveals = [script.beats[0].reveals[1].model_copy(), late]

    (found,) = problems(script, LIBRARY, "ru")

    assert found.startswith("Beat 1 brings up a graphic with style 'threat' within its first 2 s")


def test_the_schema_holds_the_counts_the_format_needs() -> None:
    with pytest.raises(ValidationError):
        Beat(location="a", pose="b", lines=["один"], delivery="", reveals=[])
    with pytest.raises(ValidationError):
        good().model_copy(update={"beats": good().beats[:8]}).model_validate(
            good().model_dump() | {"beats": [b.model_dump() for b in good().beats[:8]]}
        )


def test_a_location_needs_a_spot_for_the_hero(tmp_path: Path) -> None:
    (tmp_path / "library.toml").write_text(
        '[locations.a]\nabout = "x"\nanchors = { door = { x = 0.1, y = 0.1 } }\n[poses]\nstand = "s"\n',
        encoding="utf-8",
    )

    with pytest.raises(StageError, match="hero"):
        read_library(tmp_path)


def test_a_missing_library_is_named(tmp_path: Path) -> None:
    with pytest.raises(StageError, match=r"no series library at .*library\.toml"):
        read_library(tmp_path)


def test_the_writer_reads_every_key_of_the_library() -> None:
    menu = LIBRARY.menu()

    for key in [*LIBRARY.locations, *LIBRARY.poses, *LIBRARY.props, *LIBRARY.sfx, "floor_below"]:
        assert f"`{key}`" in menu
    assert "bare pipe → one blanket around it" in menu


async def test_draft_sends_the_problems_back_until_none_are_left() -> None:
    broken = good()
    broken.hook = "Что под полом?"
    drafts = [broken, broken, good()]
    notes: list[str | None] = []

    async def write(note: str | None) -> BeatScript:
        notes.append(note)
        return drafts.pop(0)

    script, rewrites, left = await draft(write, LIBRARY, "ru", rewrites=3)

    assert (script, rewrites, left) == (good(), 2, [])
    assert notes[0] is None
    assert notes[1] == "The first line of beat 1 is the `hook`, word for word."


async def test_draft_keeps_the_draft_with_the_fewest_problems_when_rewrites_run_out() -> None:
    worse = good()
    worse.hook = "Что под полом?"
    worse.cliffhanger = "WHO?"
    bad = good()
    bad.hook = "Что под полом?"
    drafts = [bad, worse]

    async def write(note: str | None) -> BeatScript:
        return drafts.pop(0)

    script, rewrites, left = await draft(write, LIBRARY, "ru", rewrites=1)

    assert (script, rewrites, len(left)) == (bad, 1, 1)


def test_an_empty_library_is_refused() -> None:
    with pytest.raises(ValidationError):
        Library(locations={}, poses={})
