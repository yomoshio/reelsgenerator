import shutil
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from reelsmith.app import stages_for, synthetic_services
from reelsmith.conveyor import Conveyor, Gpu
from reelsmith.models import Job, Status
from reelsmith.pricing import DEFAULT
from reelsmith.services.ffmpeg import FfmpegMontage
from reelsmith.services.synthetic import SyntheticLlm, SyntheticNarrator, SyntheticTranscriber
from reelsmith.store import MemoryJobs
from tests.fakes import REPO_STYLES, style

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")


async def test_synthetic_scripts_are_deterministic_and_rewrites_change_them() -> None:
    llm = SyntheticLlm()
    first = await llm.write("зомби в метро", style())
    second = await llm.write("зомби в метро", style())
    rewrite = await llm.write("зомби в метро", style(), "tighten the hook")

    assert first == second
    assert first.hook_kind in {"question", "threat", "promise", "secret", "countdown"}
    assert [s.line for s in first.shots] != [s.line for s in rewrite.shots]
    assert len(first.shots) == len(rewrite.shots)


@needs_ffmpeg
async def test_transcriber_spreads_words_over_the_recording(tmp_path: Path) -> None:
    montage = FfmpegMontage()
    audio = await SyntheticNarrator().speak("никто не вышел из палаты", tmp_path / "v.wav")

    words = await SyntheticTranscriber(montage).words(audio)

    assert [w.text for w in words] == ["никто", "не", "вышел", "из", "палаты"]
    assert words[0].start == 0.0
    assert words[-1].end == pytest.approx(await montage.seconds(audio), abs=0.1)


@needs_ffmpeg
async def test_end_to_end_synthetic_run_produces_a_final_cut(tmp_path: Path) -> None:
    services = synthetic_services(
        media=tmp_path / "media",
        outbox=tmp_path / "outbox",
        styles=REPO_STYLES,
        tariff=DEFAULT,
        analytics=True,
    )
    stages = [replace(s, settled=timedelta(0)) for s in stages_for(services)]
    store = MemoryJobs()
    job = Job.new("зомби в ночном метро")
    await store.add(job)
    conveyor = Conveyor(stages, store, services, Gpu({}), batch_size=4, max_attempts=5)

    while await conveyor.turn():
        pass

    assert job.status is Status.ASSEMBLED
    assert job.assets.final is not None
    final = services.media / job.assets.final
    assert final.exists()
    assert await services.montage.seconds(final) == pytest.approx(
        job.require_script().seconds, abs=1.0
    )
    assert job.assets.voices[0].endswith(".wav")
    assert {c.stage for c in job.calls} == {
        "plan", "script", "critic", "voice", "frame", "pick", "animate", "inspect", "music", "qa"
    }  # fmt: skip
    assert job.cost > 0

    job.status = Status.APPROVED
    await store.save(job)
    while await conveyor.turn():
        pass

    assert job.status is Status.MEASURED
    assert job.metrics is not None
    assert job.assets.posted is not None
    assert (Path(job.assets.posted) / "video.mp4").exists()
