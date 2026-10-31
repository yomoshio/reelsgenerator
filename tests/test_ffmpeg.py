from pathlib import Path

from reelsmith.services.ffmpeg import (
    Card,
    Cut,
    Segment,
    Word,
    captions,
    ffmpeg_args,
    shift,
    stills_args,
    to_ass,
)
from tests.fakes import style


def test_captions_group_up_to_three_words_and_break_on_pauses() -> None:
    words = [
        Word("Никто", 0.0, 0.4),
        Word("не", 0.4, 0.5),
        Word("вышел", 0.5, 0.9),
        Word("из", 1.0, 1.1),
        Word("палаты", 1.1, 1.6),
        Word("ночью", 2.8, 3.2),
    ]

    assert [c.text for c in captions(words)] == ["Никто не вышел", "из палаты", "ночью"]
    assert [len(c.words) for c in captions(words, max_words=2)] == [2, 2, 1, 1]


def test_shift_moves_words_to_the_shot_start() -> None:
    assert shift([Word("a", 0.1, 0.3, accent=True)], 4.0) == [Word("a", 4.1, 4.3, accent=True)]


def test_ass_uses_centisecond_timestamps() -> None:
    ass = to_ass(captions([Word("тихо", 61.234, 62.0)]), style())

    assert "Dialogue: 0,0:01:01.23,0:01:02.00,Caption," in ass
    assert "ТИХО" in ass


def test_karaoke_sweeps_each_word_and_colours_the_stressed_one() -> None:
    words = [
        Word("теперь", 0.0, 0.5),
        Word("выведу", 0.6, 1.2, accent=True),
        Word("тебя", 1.3, 1.8),
    ]

    ass = to_ass(captions(words), style())

    assert (
        r"Caption,{\1c&H00FFFFFF&\k60}ТЕПЕРЬ "
        r"{\1c&H001FD2FF&\k70}ВЫВЕДУ "
        r"{\1c&H00FFFFFF&\k50}ТЕБЯ"
    ) in ass


def test_captions_without_karaoke_carry_no_sweep() -> None:
    plain = style().model_copy(
        update={"captions": style().captions.model_copy(update={"karaoke": False})}
    )

    assert r"\k" not in to_ass(captions([Word("тихо", 0.0, 1.0)]), plain)


def test_plates_become_boxed_styles_and_timed_events() -> None:
    cards = [
        Card("rule", "1. Уходи, когда не ждут", 2.0, 9.5),
        Card("tag", "ночью | с фонарём", 2.0, 4.0),
        Card("unknown", "ignored", 0.0, 1.0),
    ]

    ass = to_ass([], style(), cards)

    assert "Style: Plate-rule," in ass
    assert ",&H001A1A1A,&H001A1A1A,&H00FFFFFF,&H00000000,-1,3,16,0,7," in ass
    assert "Dialogue: 1,0:00:02.00,0:00:09.50,Plate-rule," in ass
    assert r"{\1c&H001E26B3&}1.{\1c&H001A1A1A&} УХОДИ, КОГДА НЕ ЖДУТ" in ass
    assert r"НОЧЬЮ\N{\fs29\b0}С ФОНАРЁМ" in ass
    assert "ignored" not in ass.lower()


def test_text_cannot_inject_ass_override_tags() -> None:
    ass = to_ass(
        captions([Word(r"{\fs1}ой", 0.0, 1.0)]), style(), [Card("tag", r"a{\b1}b", 0.0, 1.0)]
    )

    assert r"{\fs1}" not in ass
    assert r"{\b1}" not in ass


def test_ffmpeg_graph_trims_every_shot_to_its_voice_length() -> None:
    cut = Cut(
        segments=(
            Segment(Path("c0.mp4"), Path("v0.wav"), 3.2),
            Segment(Path("c1.mp4"), Path("v1.wav"), 4.75),
        ),
        music=Path("m.flac"),
        subtitles=Path("/data/media/x/subtitles.ass"),
    )

    args = ffmpeg_args(cut, Path("out.mp4"))
    graph = args[args.index("-filter_complex") + 1]

    assert "[0:v]tpad=stop_mode=clone:stop_duration=3.200,trim=duration=3.200" in graph
    assert "[2:v]tpad=stop_mode=clone:stop_duration=4.750,trim=duration=4.750" in graph
    assert "[3:a]aresample=48000,apad=whole_dur=4.750,atrim=duration=4.750[a1]" in graph
    assert "[4:a]aresample=48000,volume=" in graph
    assert "subtitles=filename='/data/media/x/subtitles.ass'" in graph
    assert args[-1] == "out.mp4"


def test_music_level_is_a_parameter() -> None:
    cut = Cut((Segment(Path("c.mp4"), Path("v.wav"), 3.0),), Path("m.flac"), Path("/s.ass"))

    assert "volume=0.4[bed]" in " ".join(ffmpeg_args(cut, Path("o.mp4"), music_level=0.4))


def test_stills_args_spaces_frames_over_the_clip() -> None:
    args = stills_args(Path("c.mp4"), 4, 5.0, Path("/out"))

    assert args[args.index("-vf") + 1] == "fps=1/1.250,scale=540:-2"
    assert args[args.index("-frames:v") + 1] == "4"
    assert args[-1] == "/out/%02d.png"
    wide = stills_args(Path("c.mp4"), 4, 5.0, Path("/out"), width=1080)
    assert wide[wide.index("-vf") + 1] == "fps=1/1.250,scale=1080:-2"
