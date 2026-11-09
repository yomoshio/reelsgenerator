import asyncio
import shutil
import subprocess
from itertools import accumulate
from pathlib import Path

import pytest
from PIL import Image

from reelsmith import graphics
from reelsmith.beats import EXAMPLES, Beat, BeatScript, Reveal, beat_seconds, read_library
from reelsmith.graphics import SCENE_BOTTOM, Sprite, state
from reelsmith.render import (
    TAIL,
    frames,
    mix_args,
    plan,
    render,
    sheet,
    starts,
    timing,
)
from reelsmith.services.ffmpeg import Word
from reelsmith.styles import Styles
from tests.fakes import REPO_STYLES

PROTO = Path(__file__).resolve().parent.parent / "studio" / "series" / "proto"
LIBRARY = read_library(PROTO)
SILENCE = EXAMPLES[0]
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")


def heard_from(beat: Beat, *, every: float = 0.4, swap: dict[str, str] | None = None) -> list[Word]:
    """A transcript of the beat as whisper would give it: a word every `every` seconds,
    with some words heard differently."""
    swap = swap or {}
    texts = [swap.get(t, t) for t in beat.text.replace("—", " ").split()]
    return [Word(t, 0.2 + i * every, 0.2 + i * every + every * 0.8) for i, t in enumerate(texts)]


def test_words_without_a_voice_follow_each_other_with_pauses_after_sentences() -> None:
    said = timing(SILENCE)

    starts_ = [w.start for w in said.shown]
    assert starts_ == sorted(starts_)
    assert said.shown[0].start == pytest.approx(0.15)
    shown = [w.text for w in said.shown]
    assert shown[shown.index("Поэтому") : shown.index("Поэтому") + 3] == [
        "Поэтому",
        "первое —",
        "тишина.",
    ]
    after_sentence = said.shown[4].start - said.shown[3].end
    between_words = said.shown[3].start - said.shown[2].end
    assert after_sentence > 0.2
    assert between_words == 0


def test_without_a_voice_a_beat_runs_as_long_as_the_checks_expect() -> None:
    said = timing(SILENCE)

    assert said.end - said.shown[0].start == pytest.approx(beat_seconds(SILENCE))


def test_each_graphic_comes_up_exactly_when_whisper_hears_its_word() -> None:
    heard = heard_from(SILENCE)
    said = timing(SILENCE, heard)

    by_text = {w.text.strip(",.").lower(): w.start for w in heard}
    for reveal, at in zip(SILENCE.reveals, starts(SILENCE, said), strict=True):
        assert at == pytest.approx(by_text[reveal.on_word], abs=0.1)


def test_a_word_heard_differently_takes_the_time_of_what_was_heard_in_its_place() -> None:
    beat = Beat(
        location="riser_room",
        pose="stand",
        lines=["Через двадцать минут свет гаснет.", "Нина ждёт."],
        delivery="calm",
        reveals=[Reveal(on_word="двадцать", kind="hud", text="00:20")],
    )
    heard = heard_from(beat, swap={"двадцать": "20"})

    said = timing(beat, heard)

    assert starts(beat, said) == [pytest.approx(heard[1].start)]
    assert [w.text for w in said.shown] == beat.text.split()


def test_words_whisper_missed_share_the_gap_between_their_neighbours() -> None:
    heard = [w for w in heard_from(SILENCE) if w.text != "легко"]

    said = timing(SILENCE, heard)

    gone = next(i for i, w in enumerate(said.shown) if w.text == "легко")
    assert said.shown[gone - 1].end <= said.shown[gone].start < said.shown[gone + 1].start


def test_the_rule_card_carries_into_the_next_beat_until_a_new_one_replaces_it() -> None:
    first = plan(SILENCE, LIBRARY, PROTO, timing(SILENCE), seconds=12.0)
    second_beat = SILENCE.model_copy(
        update={
            "reveals": [Reveal(on_word="Марк", kind="rule_card", text="2. свет", persist="episode")]
        }
    )
    second_said = timing(second_beat)

    second = plan(second_beat, LIBRARY, PROTO, second_said, seconds=12.0, carried=first.carried)

    assert [s.kind for s in first.carried] == ["rule_card"]
    old, new = (s for s in second.sprites if s.kind == "rule_card")
    assert old.start == 0.0
    assert old.end == pytest.approx(starts(second_beat, second_said)[0])
    assert second.carried == [new]


def test_a_prop_stage_wraps_bands_round_the_prop_from_the_floor_up() -> None:
    said = timing(SILENCE)
    laid = plan(SILENCE, LIBRARY, PROTO, said, seconds=said.end + TAIL)

    bands = [s for s in laid.sprites if s.kind == "prop_stage"]
    assert len(bands) == graphics.BANDS
    floor = LIBRARY.locations["riser_room"].anchors["hero"].y * graphics.H
    assert bands[0].xy[1] + bands[0].image.height == pytest.approx(floor + 4, abs=1)
    assert [b.start for b in bands] == sorted(b.start for b in bands)


def test_a_pose_reveal_switches_the_hero_on_its_word() -> None:
    beat = SILENCE.model_copy(
        update={"reveals": [Reveal(on_word="тишина", kind="pose", target="knock")]}
    )
    said = timing(beat)

    laid = plan(beat, LIBRARY, PROTO, said, seconds=said.end + TAIL)

    assert [t for t, _ in laid.backgrounds] == [0.0, starts(beat, said)[0]]


def test_graphics_stay_in_the_frame_and_above_the_captions() -> None:
    for example in EXAMPLES:
        said = timing(example)
        laid = plan(example, LIBRARY, PROTO, said, seconds=said.end + TAIL)
        for s in laid.sprites:
            x, y = s.xy
            assert x >= 0
            assert y >= 0
            assert x + s.image.width <= graphics.W
            assert y + s.image.height <= SCENE_BOTTOM, (s.kind, y + s.image.height)


def test_the_hand_on_the_pipe_reaches_the_pipe() -> None:
    anchors = LIBRARY.locations["riser_room"].anchors
    figure = graphics.hero("hand_on_pipe", anchors)
    pipe_x = anchors["pipe"].x * graphics.W
    alpha = figure.image.getchannel("A")
    row = round(figure.image.height - 0.64 * graphics.HERO_HEIGHT)
    reach = max(x for x in range(figure.image.width) if alpha.getpixel((x, row)))

    assert figure.xy[0] + reach == pytest.approx(pipe_x, abs=20)


@pytest.mark.parametrize("key", list(LIBRARY.locations))
def test_stand_in_scenes_are_as_dark_as_the_reference(key: str) -> None:
    img = graphics.scene(key, LIBRARY.locations[key]).convert("L")
    top = img.crop((0, 0, graphics.W, round(graphics.H * 0.55))).resize((180, 176))
    counts = list(accumulate(top.histogram()))
    median = next(v for v, c in enumerate(counts) if c >= counts[-1] / 2)

    assert 18 <= median <= 40


def test_a_sprite_is_hidden_before_its_start_animating_then_settled() -> None:
    sprite = Sprite(Image.new("RGBA", (10, 10)), (0, 0), start=1.0, end=3.0, lasts=0.2)

    assert [state(sprite, t, 30) for t in (0.9, 1.0, 1.1, 1.3, 2.9, 3.0)] == [
        None,
        0,
        3,
        -1,
        -1,
        None,
    ]


def test_a_still_stretch_repeats_one_frame_instead_of_composing_again() -> None:
    said = timing(SILENCE)
    laid = plan(SILENCE, LIBRARY, PROTO, said, seconds=2.0)

    made = list(frames(laid, fps=10))

    assert len(made) == 20
    assert len({id(f) for f in made}) == 1
    assert len(made[0]) == graphics.W * graphics.H * 3


def test_the_storyboard_puts_every_beat_in_rows_of_six() -> None:
    script = BeatScript(
        title="Тишина", part=3, hook=SILENCE.lines[0], hud="ДЕНЬ 3 · 02:41",
        beats=[SILENCE] * 9, cliffhanger="КТО ПОД НАМИ?", music="drone",
    )  # fmt: skip

    made = sheet(script, LIBRARY, PROTO, width=90)

    assert made.size == (6 * 90, 2 * 160)


def test_the_mix_ducks_the_bed_softly_and_ends_in_48k_stereo(tmp_path: Path) -> None:
    args = mix_args(
        tmp_path / "voice.wav",
        [(tmp_path / "pop.wav", 1.234)],
        [tmp_path / "room.wav", tmp_path / "drone.wav"],
        10.0,
        tmp_path / "out.wav",
    )
    graph = args[args.index("-filter_complex") + 1]

    assert "sidechaincompress=threshold=0.05:ratio=3.5" in graph
    assert "[floor]volume=0.25[low]" in graph
    assert "adelay=1234|1234" in graph
    assert graph.index("loudnorm") < graph.rindex("aresample=48000")
    assert args[-5:-1] == ["-ar", "48000", "-ac", "2"]


def test_without_a_voice_the_bed_plays_undocked_and_without_anything_silence(
    tmp_path: Path,
) -> None:
    bed_only = mix_args(None, [], [tmp_path / "room.wav"], 5.0, tmp_path / "out.wav")
    nothing = mix_args(None, [], [], 5.0, tmp_path / "out.wav")

    assert "sidechaincompress" not in bed_only[bed_only.index("-filter_complex") + 1]
    assert "anullsrc=r=48000:cl=stereo:d=5.000" in nothing


@needs_ffmpeg
def test_a_beat_renders_to_a_vertical_video_with_48k_stereo_sound(tmp_path: Path) -> None:
    voice = tmp_path / "voice.wav"
    sine = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=180:d=3", "-ar", "24000"]
    subprocess.run([*sine, str(voice)], check=True)
    beat = Beat(
        location="riser_room", pose="hand_on_pipe", lines=["Марк слушает.", "Тишина."],
        delivery="calm", reveals=[Reveal(on_word="тишина", kind="rule_card", text="1. тишина")],
        sfx=["card_pop"],
    )  # fmt: skip
    heard = [Word("Марк", 0.2, 0.5), Word("слушает.", 0.5, 1.1), Word("Тишина.", 1.5, 2.2)]
    out = tmp_path / "beat.mp4"
    style = Styles(REPO_STYLES).get("rules-beats")

    laid = asyncio.run(
        render(beat, LIBRARY, PROTO, style, out, voice=voice, heard=heard, voice_seconds=3.0)
    )

    assert laid.seconds == 3.0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,sample_rate,channels",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert probe == ["1080,1920", "48000,2"]
