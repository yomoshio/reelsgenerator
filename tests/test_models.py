from uuid import uuid4

import pytest
from pydantic import ValidationError

from reelsmith.models import Call, Character, Job, Recipe, Script, Shot, Status
from tests.fakes import recipe


def _shot(line: str, cast: list[str] | None = None) -> Shot:
    return Shot(line=line, picture="corridor", motion="slow push in", cast=cast or [], stress=["x"])


def _script() -> Script:
    return Script(
        title="t",
        hook="h",
        hook_kind="question",
        characters=[Character(name="Vera", look="nurse, 30s")],
        shots=[_shot("a", ["Vera"]), _shot("b"), _shot("c")],
        music="drone",
    )


def test_status_walks_the_whole_conveyor() -> None:
    walked = [Status.NEW]
    while walked[-1] is not Status.MEASURED:
        walked.append(walked[-1].next())

    assert walked == [s for s in Status if s is not Status.FAILED]


@pytest.mark.parametrize("terminal", [Status.MEASURED, Status.FAILED])
def test_terminal_status_has_no_next(terminal: Status) -> None:
    with pytest.raises(ValueError, match="terminal"):
        terminal.next()


def test_video_for_routes_the_hook_shots() -> None:
    routed = recipe(video="wan-5b", hook_video="wan-2.2", hook_shots=2)

    assert [routed.video_for(i) for i in range(3)] == ["wan-2.2", "wan-2.2", "wan-5b"]
    assert recipe().video_for(0) == "fast"


def test_still_shots_go_to_the_calm_model_after_the_hook() -> None:
    routed = Recipe(video="wan-2.2", hook_video="wan-5b", hook_shots=1, calm_video="still")

    assert routed.video_for(0, moves=False) == "wan-5b"
    assert routed.video_for(1, moves=False) == "still"
    assert routed.video_for(1, moves=True) == "wan-2.2"
    assert Recipe(video="wan-2.2").video_for(3, moves=False) == "wan-2.2"


def test_looks_only_include_characters_in_frame() -> None:
    script = _script()
    script.characters.append(Character(name="Ilya", look="boy, 9"))
    script.shots[2].cast = ["Ilya", "Vera"]

    assert script.looks_of(script.shots[0]) == "nurse, 30s"
    assert script.looks_of(script.shots[1]) == ""
    assert script.looks_of(script.shots[2]) == "nurse, 30s boy, 9"


def test_script_rejects_too_few_shots() -> None:
    with pytest.raises(ValidationError):
        Script(title="t", hook="h", hook_kind="q", characters=[], shots=[_shot("a")], music="m")


def test_fail_parks_the_job_at_the_limit() -> None:
    job = Job.new("zombies")
    job.status = Status.SCRIPTED

    job.fail("tts down", max_attempts=3)
    job.fail("tts down", max_attempts=3)
    assert (job.status, job.attempts, job.last_error) == (Status.SCRIPTED, 2, "tts down")

    job.fail("tts down", max_attempts=3)
    assert (job.status, job.attempts) == (Status.FAILED, 3)


def test_rewind_moves_back_and_counts_an_attempt() -> None:
    job = Job.new("zombies")
    job.status = Status.ASSEMBLED

    job.rewind(Status.FRAMED, "shot 2 drifts", max_attempts=2)
    assert (job.status, job.attempts, job.last_error) == (Status.FRAMED, 1, "shot 2 drifts")

    job.status = Status.ASSEMBLED
    job.rewind(Status.FRAMED, "still drifts", max_attempts=2)
    assert job.status is Status.FAILED


def test_reject_drops_the_clips_and_rewinds_to_frames() -> None:
    job = Job.new("zombies")
    job.status = Status.ASSEMBLED
    job.assets.clips = {0: "clips/00.mp4"}
    job.assets.final = "final.mp4"

    job.reject("wrong mood", max_attempts=3)

    assert (job.status, job.attempts, job.last_error) == (Status.FRAMED, 1, "wrong mood")
    assert (job.assets.clips, job.assets.final) == ({}, None)


def test_fork_starts_at_frames_with_shared_calls() -> None:
    parent = Job.new("zombies", recipe())
    parent.status = Status.ASSEMBLED
    parent.script = _script()
    parent.assets.frames = {0: "frames/00-1.png"}
    parent.assets.candidates = {0: ["frames/00-0.png", "frames/00-1.png"]}
    parent.assets.voices = {0: "voice/00.wav"}
    parent.assets.clips = {0: "clips/00.mp4"}
    parent.assets.music = "music.flac"
    parent.assets.final = "final.mp4"
    parent.calls.append(Call(stage="animate", provider="fast", units=5, usd=0.5))

    child = parent.fork(recipe(video="slow"), "B")

    assert child.id != parent.id
    assert child.parent == parent.id
    assert (parent.experiment, parent.arm) == (str(parent.id), "A")
    assert (child.experiment, child.arm) == (str(parent.id), "B")
    assert child.status is Status.FRAMED
    assert child.recipe.video == "slow"
    assert child.script == parent.script
    assert child.assets.frames == parent.assets.frames
    assert child.assets.candidates == parent.assets.candidates
    assert child.assets.voices == parent.assets.voices
    assert (child.assets.clips, child.assets.music, child.assets.final) == ({}, None, None)
    assert child.calls[0].shared is True
    assert child.cost == parent.cost == 0.5
    assert child.spent == 0

    child.assets.frames[1] = "frames/01-0.png"
    assert 1 not in parent.assets.frames


def test_fork_of_a_scripted_job_keeps_its_status() -> None:
    parent = Job.new("zombies", experiment="hooks", arm="question")
    parent.status = Status.SCRIPTED
    parent.script = _script()

    child = parent.fork(recipe(), "threat")

    assert child.status is Status.SCRIPTED
    assert (parent.experiment, parent.arm) == ("hooks", "question")
    assert child.experiment == "hooks"


def test_cost_sums_calls() -> None:
    job = Job.new("zombies")
    job.calls += [
        Call(stage="frame", provider="z-image", units=1, usd=0.067),
        Call(stage="animate", provider="wan-2.2", units=5, usd=0.5),
    ]

    assert job.cost == pytest.approx(0.567)
    assert job.good is False
    job.status = Status.APPROVED
    assert job.good is True


def test_job_id_is_unique_per_new_job() -> None:
    assert Job.new("a").id != Job.new("a").id
    assert isinstance(uuid4(), type(Job.new("a").id))
