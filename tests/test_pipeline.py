import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from reelsmith.models import (
    Call,
    Job,
    Metrics,
    Outcome,
    Overlay,
    Post,
    Rewind,
    StageError,
    Status,
    Verdict,
)
from reelsmith.pipeline import (
    STAGES,
    Files,
    Gates,
    _cards,
    animate,
    assemble,
    check,
    measure,
    paint,
    pick,
    publish,
    score,
    voice,
    write,
)
from reelsmith.services.outbox import OutboxPublisher
from tests.fakes import (
    FakeAnalytics,
    FakeAnimator,
    FakeComposer,
    FakeLlm,
    FakeMontage,
    FakeNarrator,
    FakePainter,
    FakePublisher,
    job,
    recipe,
    script,
    services,
    style,
)


def _stages(job: Job) -> list[str]:
    return [c.stage for c in job.calls]


def _framed(shots: int = 3, **recipe_overrides: object) -> Job:
    made = job(status=Status.FRAMED, recipe=recipe(**recipe_overrides), script=script(shots))
    made.assets.frames = {i: f"frames/{i:02d}-0.png" for i in range(shots)}
    return made


def _animated(shots: int = 3, *, tries: dict[int, int] | None = None) -> Job:
    made = _framed(shots)
    made.status = Status.ANIMATED
    for i in range(shots):
        made.assets.clips[i] = f"clips/{i:02d}.mp4"
        for _ in range((tries or {}).get(i, 1)):
            made.calls.append(Call(stage="animate", provider="fast", units=4, usd=0.4, shot=i))
    return made


def test_stages_cover_every_automatic_status() -> None:
    automatic = [s for s in Status if s not in (Status.ASSEMBLED, Status.MEASURED, Status.FAILED)]

    assert [s.takes for s in STAGES] == automatic
    assert all(s.gpu in {"llm", "tts", "comfy", None} for s in STAGES)


def test_files_name_candidates_and_stills(tmp_path: Path) -> None:
    files = Files(tmp_path, UUID(int=7))

    assert files.frame(3, 1).relative_to(files.base) == Path("frames/03-1.png")
    assert files.voice(0, ".mp3").relative_to(files.base) == Path("voice/00.mp3")
    assert files.music(".mp3").relative_to(files.base) == Path("music.mp3")
    assert files.stills(2).relative_to(files.base) == Path("stills/02")
    assert files.stills(None).relative_to(files.base) == Path("stills/final")
    assert files.stills(2).is_dir()


async def test_write_rewrites_with_the_critics_notes_until_it_passes(tmp_path: Path) -> None:
    llm = FakeLlm(scores=[5.0, 8.0])
    made = job()

    await write(made, services(tmp_path, llm=llm))

    assert llm.written == [("zombies", None), ("zombies", "tighten the hook")]
    assert made.require_script().title == "zombies draft 2"
    assert made.critique is not None
    assert made.critique.score == 8.0
    assert _stages(made) == ["script", "critic", "script", "critic"]


async def test_best_draft_is_kept_after_the_last_rewrite(tmp_path: Path) -> None:
    llm = FakeLlm(scores=[6.0, 5.0, 6.5])
    made = job()

    await write(made, services(tmp_path, llm=llm))

    assert len(llm.written) == 3
    assert made.require_script().title == "zombies draft 3"
    assert made.critique is not None
    assert made.critique.score == 6.5


async def test_voice_sets_shot_seconds_from_the_recording(tmp_path: Path) -> None:
    narrator = FakeNarrator(suffix=".mp3")
    made = job(status=Status.SCRIPTED, script=script(3))

    await voice(made, services(tmp_path, narrator=narrator, montage=FakeMontage(3.0)))

    assert [s.seconds for s in made.require_script().shots] == [3.35, 3.35, 3.35]
    assert made.assets.voices == {i: f"{made.id}/voice/{i:02d}.mp3" for i in range(3)}
    assert [(c.stage, c.units, c.shot) for c in made.calls] == [("voice", 6, i) for i in range(3)]


async def test_paint_makes_two_candidates_per_shot_and_skips_done_shots(tmp_path: Path) -> None:
    painter = FakePainter()
    made = job(status=Status.VOICED, script=script(3))
    made.assets.candidates[0] = ["x/frames/00-0.png", "x/frames/00-1.png"]

    await paint(made, services(tmp_path, painter=painter))

    assert made.assets.candidates[1] == [f"{made.id}/frames/01-{k}.png" for k in range(2)]
    assert {c.shot for c in made.calls} == {1, 2}
    assert _stages(made).count("frame") == 4
    prompt, _ = painter.log[0]
    assert prompt == "nurse, 30s, grey cardigan. picture 1. FRAME"
    assert len({seed for _, seed in painter.log}) == 4


async def test_gates_set_how_many_frames_are_painted(tmp_path: Path) -> None:
    painter = FakePainter()
    made = job(status=Status.VOICED, script=script(3))

    await paint(made, replace(services(tmp_path, painter=painter), gates=Gates(candidates=1)))

    assert [len(c) for c in made.assets.candidates.values()] == [1, 1, 1]


async def test_pick_chooses_among_the_candidates(tmp_path: Path) -> None:
    llm = FakeLlm(picks=1)
    made = job(status=Status.PAINTED, script=script(3))
    made.assets.candidates = {i: [f"x/frames/{i:02d}-{k}.png" for k in range(2)] for i in range(3)}

    await pick(made, services(tmp_path, llm=llm))

    assert made.assets.frames == {i: f"x/frames/{i:02d}-1.png" for i in range(3)}
    assert [c.stage for c in made.calls] == ["pick"] * 3
    assert llm.log[0][1] == [tmp_path / "x/frames/00-0.png", tmp_path / "x/frames/00-1.png"]


async def test_animate_routes_hook_shots_and_skips_done_shots(tmp_path: Path) -> None:
    main, hook = FakeAnimator("fast"), FakeAnimator("hook")
    made = _framed(3, video="fast", hook_video="hook", hook_shots=1)
    made.assets.clips[2] = "clips/02.mp4"

    await animate(made, services(tmp_path, animators={"fast": main, "hook": hook}))

    assert len(hook.log) == 1
    assert len(main.log) == 1
    assert {c.provider for c in made.calls if c.shot == 0} == {"hook"}
    assert made.assets.clips == {
        0: f"{made.id}/clips/00.mp4",
        1: f"{made.id}/clips/01.mp4",
        2: "clips/02.mp4",
    }


async def test_animate_seeds_change_with_the_attempt(tmp_path: Path) -> None:
    animator = FakeAnimator("fast")
    made = _framed(3)
    s = services(tmp_path, animators={"fast": animator})

    await animate(made, s)
    first = {frame.name: seed for frame, _, _, seed in animator.log}
    animator.log.clear()
    made.assets.clips.clear()
    made.attempts = 1
    await animate(made, s)
    second = {frame.name: seed for frame, _, _, seed in animator.log}

    assert first.keys() == second.keys()
    assert all(first[name] != second[name] for name in first)


async def test_animate_caps_the_clip_and_bills_what_the_model_generates(tmp_path: Path) -> None:
    animator = FakeAnimator("fast", max_seconds=5.0)
    made = _framed(3)
    made.require_script().shots[0].seconds = 7.5

    await animate(made, services(tmp_path, animators={"fast": animator}))

    assert {frame.name: seconds for frame, _, seconds, _ in animator.log}["00-0.png"] == 5.0
    assert sorted(c.units for c in made.calls) == [4.0, 4.0, 5.0]


async def test_unknown_model_fails_the_job_not_the_worker(tmp_path: Path) -> None:
    made = _framed(3, video="veo")

    with pytest.raises(StageError, match="no video model named 'veo'; have: fast, slow"):
        await animate(made, services(tmp_path))


async def test_check_drops_flagged_clips_and_rewinds(tmp_path: Path) -> None:
    llm = FakeLlm(flag={1})
    made = _animated(3)

    with pytest.raises(Rewind) as back:
        await check(made, services(tmp_path, llm=llm))

    assert back.value.to is Status.FRAMED
    assert set(made.assets.clips) == {0, 2}
    animated = [c for c in made.calls if c.stage == "animate"]
    assert [c.outcome for c in animated] == [Outcome.OK, Outcome.FLAGGED, Outcome.OK]
    assert _stages(made).count("inspect") == 3


async def test_check_does_not_judge_a_clip_twice(tmp_path: Path) -> None:
    llm = FakeLlm(flag={1})
    made = _animated(3)
    with pytest.raises(Rewind):
        await check(made, services(tmp_path, llm=llm))
    made.calls.append(Call(stage="animate", provider="fast", units=4, usd=0.1, shot=1))
    made.assets.clips[1] = "clips/01.mp4"

    await check(made, services(tmp_path, llm=FakeLlm(flag={1, 2})))

    inspected = [c.shot for c in made.calls if c.stage == "inspect"]
    assert inspected == [0, 1, 2, 1]
    assert set(made.assets.clips) == {0, 1, 2}


async def test_check_keeps_a_clip_after_its_tries(tmp_path: Path) -> None:
    llm = FakeLlm(flag={0})
    made = _animated(3, tries={0: 3})

    await check(made, services(tmp_path, llm=llm))

    assert set(made.assets.clips) == {0, 1, 2}
    assert [c.outcome for c in made.calls if c.stage == "animate" and c.shot == 0][
        -1
    ] is Outcome.FLAGGED


async def test_score_covers_the_script_plus_two_seconds_and_runs_once(tmp_path: Path) -> None:
    composer = FakeComposer(suffix=".mp3")
    made = job(status=Status.CHECKED, script=script(3))
    s = services(tmp_path, composer=composer)

    await score(made, s)
    await score(made, s)

    assert composer.log == [("slow drone", 14.0)]
    assert made.assets.music == f"{made.id}/music.mp3"
    assert [(c.stage, c.units) for c in made.calls] == [("music", 14.0)]


def _scored(shots: int = 3) -> Job:
    made = job(status=Status.SCORED, script=script(shots))
    made.assets.voices = {i: f"voice/{i:02d}.wav" for i in range(shots)}
    made.assets.clips = {i: f"clips/{i:02d}.mp4" for i in range(shots)}
    made.assets.music = "music.flac"
    return made


async def test_assemble_renders_and_passes_qa(tmp_path: Path) -> None:
    llm, montage = FakeLlm(), FakeMontage()
    made = _scored()

    await assemble(made, services(tmp_path, llm=llm, montage=montage))

    assert made.assets.final == f"{made.id}/final.mp4"
    assert made.qa is not None
    assert made.qa.score == 8.5
    assert len(montage.rendered[0].segments) == 3
    assert (tmp_path / str(made.id) / "subtitles.ass").exists()
    kind, stills = llm.log[-1]
    assert (kind, len(stills)) == ("judge", 3)
    assert montage.moments == [2.0, 6.0, 10.0]
    assert _stages(made) == ["qa"]


async def test_assemble_puts_overlays_and_stressed_words_on_the_timeline(tmp_path: Path) -> None:
    made = _scored()
    shots = made.require_script().shots
    shots[0].overlays = [
        Overlay(kind="rule", text="1. Уходи", hold=2),
        Overlay(kind="nope", text="x"),
    ]
    shots[1].overlays = [Overlay(kind="tag", text="ночью")]
    shots[0].stress = ["line"]

    await assemble(made, services(tmp_path))

    ass = (tmp_path / str(made.id) / "subtitles.ass").read_text(encoding="utf-8")
    assert "Dialogue: 1,0:00:00.00,0:00:08.00,Plate-rule," in ass
    assert "Dialogue: 1,0:00:04.00,0:00:08.00,Plate-tag," in ass
    assert "nope" not in ass
    assert ass.count("&H001FD2FF&") == 1


def test_a_new_overlay_of_the_same_kind_ends_the_previous_one() -> None:
    made = script(5)
    shots = made.shots
    shots[0].overlays = [
        Overlay(kind="rule", text="1. A", hold=5),
        Overlay(kind="tag", text="t", hold=5),
    ]
    shots[3].overlays = [Overlay(kind="rule", text="2. B", hold=2)]

    cards = _cards(made, style(), [0.0, 4.0, 8.0, 12.0, 16.0])

    spans = {(c.text, c.start, c.end) for c in cards}
    assert spans == {("1. A", 0.0, 12.0), ("t", 0.0, 20.0), ("2. B", 12.0, 20.0)}


async def test_write_rejects_a_script_outside_the_styles_shot_range(tmp_path: Path) -> None:
    llm = FakeLlm(scores=[9.0], shots=[12, 11, 5])
    made = job()

    await write(made, services(tmp_path, llm=llm))

    assert len(made.require_script().shots) == 5
    assert [n for _, n in llm.written][1:] == [
        "The script has 12 shots; this channel needs 3 to 10. tighten the hook",
        "The script has 11 shots; this channel needs 3 to 10. tighten the hook",
    ]


async def test_qa_ignores_shot_numbers_the_script_does_not_have(tmp_path: Path) -> None:
    llm = FakeLlm(reject=Verdict(score=5.0, notes="drift", bad_shots=[2, 17]))
    made = _scored()

    with pytest.raises(Rewind):
        await assemble(made, services(tmp_path, llm=llm))

    assert made.qa is not None
    assert made.qa.bad_shots == [2]
    assert set(made.assets.clips) == {0, 1}


async def test_qa_rejection_rewinds_and_drops_only_the_bad_clips(tmp_path: Path) -> None:
    llm = FakeLlm(reject=Verdict(score=5.0, notes="shot 1 drifts", bad_shots=[1]))
    made = _scored()

    with pytest.raises(Rewind) as back:
        await assemble(made, services(tmp_path, llm=llm))

    assert back.value.to is Status.FRAMED
    assert back.value.reason == "shot 1 drifts"
    assert set(made.assets.clips) == {0, 2}
    assert made.assets.final is None
    assert made.qa is not None
    assert made.qa.score == 5.0


async def test_qa_rejection_without_named_shots_drops_every_clip(tmp_path: Path) -> None:
    made = _scored()

    with pytest.raises(Rewind):
        await assemble(made, services(tmp_path, llm=FakeLlm(reject=Verdict(score=3.0))))

    assert made.assets.clips == {}


async def test_publish_records_the_reference_and_hook_kind(tmp_path: Path) -> None:
    publisher = FakePublisher()
    made = job(status=Status.APPROVED, script=script(hook_kind="threat", title="Night shift"))
    made.assets.final = f"{made.id}/final.mp4"

    await publish(made, services(tmp_path, publisher=publisher))

    assert made.assets.posted == f"posted/{made.id}"
    assert publisher.log == [Post(caption="Night shift", hook_kind="threat")]


async def test_measure_stores_metrics_or_explains_how_to(tmp_path: Path) -> None:
    made = job(status=Status.PUBLISHED, script=script())
    made.assets.posted = "posted/x"

    with pytest.raises(StageError, match="reelsmith measure"):
        await measure(made, services(tmp_path))

    await measure(made, services(tmp_path, analytics=FakeAnalytics(retention=0.42)))

    assert made.metrics == Metrics(views=1000, retention_3s=0.42, completion=0.3)


async def test_outbox_post_json_marks_ai_content(tmp_path: Path) -> None:
    video = tmp_path / "media" / "job" / "final.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"mp4")

    posted = await OutboxPublisher(tmp_path / "outbox").publish(
        video, Post(caption="c", hook_kind="secret")
    )

    meta = json.loads((Path(posted) / "post.json").read_text())
    assert meta == {"caption": "c", "hook_kind": "secret", "is_aigc": True}
    assert (Path(posted) / "video.mp4").read_bytes() == b"mp4"
