from pathlib import Path

from reelsmith.services.ffmpeg import (
    Cut,
    Segment,
    Word,
    captions,
    ffmpeg_args,
    shift,
    stills_args,
    to_ass,
)


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


def test_shift_moves_words_to_the_shot_start() -> None:
    assert shift([Word("a", 0.1, 0.3)], 4.0) == [Word("a", 4.1, 4.3)]


def test_ass_uses_centisecond_timestamps() -> None:
    ass = to_ass([Word("тихо", 61.234, 62.0)])

    assert "Dialogue: 0,0:01:01.23,0:01:02.00,Caption,ТИХО" in ass


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


def test_stills_args_spaces_frames_over_the_clip() -> None:
    args = stills_args(Path("c.mp4"), 4, 5.0, Path("/out"))

    assert args[args.index("-vf") + 1] == "fps=1/1.250"
    assert args[args.index("-frames:v") + 1] == "4"
    assert args[-1] == "/out/%02d.png"
