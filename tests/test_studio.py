import json
import shutil
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from reelsmith.app import stages_for, synthetic_services
from reelsmith.conveyor import Conveyor, Gpu
from reelsmith.models import Job, Recipe, Status
from reelsmith.pipeline import showcase_name
from reelsmith.pricing import DEFAULT
from reelsmith.series import make_serial
from reelsmith.services.synthetic import SyntheticLlm
from reelsmith.store import MemoryJobs
from reelsmith.studio import Studio
from reelsmith.styles import Style, Styles
from tests.fakes import REPO_STYLES, script


def _studio(folder: Path, store: MemoryJobs, calls: list[str]) -> Studio:
    async def series(synopsis: str, style: Style, episodes: int):  # type: ignore[no-untyped-def]
        return await make_serial(SyntheticLlm(), synopsis, style, episodes)

    async def before_llm() -> None:
        calls.append("llm")

    return Studio(
        folder,
        store,
        recipe=Recipe(style="noir", video="wan-2.2", calm_video="still"),
        styles=Styles(REPO_STYLES),
        make_serial=series,
        before_llm=before_llm,
    )


def _drop(folder: Path, name: str, request: dict[str, object]) -> None:
    (folder / "inbox").mkdir(parents=True, exist_ok=True)
    (folder / "inbox" / f"{name}.json").write_text(
        json.dumps(request, ensure_ascii=False), encoding="utf-8"
    )


async def test_a_video_request_becomes_a_job_with_the_chosen_style_and_animation(
    tmp_path: Path,
) -> None:
    store = MemoryJobs()
    _drop(
        tmp_path,
        "a",
        {
            "kind": "video",
            "story": "Утром квартира затоплена",
            "style": "serial",
            "animation": "still",
        },
    )

    await _studio(tmp_path, store, []).sync()

    (job,) = await store.find()
    assert job.idea == "Утром квартира затоплена"
    assert (job.recipe.style, job.recipe.video, job.recipe.calm_video) == ("serial", "still", None)
    assert not list((tmp_path / "inbox").glob("*.json"))
    assert (tmp_path / "inbox" / "done" / "a.txt").read_text(encoding="utf-8").startswith("queued")


async def test_approve_finds_the_job_by_its_short_id(tmp_path: Path) -> None:
    store = MemoryJobs()
    ready, busy = Job.new("маяк"), Job.new("лифт")
    ready.status, busy.status = Status.ASSEMBLED, Status.FRAMED
    await store.add(ready)
    await store.add(busy)
    _drop(tmp_path, "a", {"kind": "approve", "job": ready.id.hex[:8]})
    _drop(tmp_path, "b", {"kind": "approve", "job": busy.id.hex[:8]})

    await _studio(tmp_path, store, []).sync()

    assert (await store.get(ready.id)).status is Status.APPROVED
    assert (await store.get(busy.id)).status is Status.FRAMED
    assert "not assembled" in (tmp_path / "inbox" / "done" / "b.txt").read_text(encoding="utf-8")


async def test_a_series_request_writes_the_files_and_can_queue_every_episode(
    tmp_path: Path,
) -> None:
    store, calls = MemoryJobs(), []
    _drop(
        tmp_path,
        "s",
        {
            "kind": "series",
            "story": "Ночью прорвало дамбу",
            "name": "flood",
            "episodes": 3,
            "style": "serial",
            "queue": True,
        },
    )

    await _studio(tmp_path, store, calls).sync()

    assert calls == ["llm"]
    assert (tmp_path / "series" / "flood.md").exists()
    jobs = await store.find()
    assert len(jobs) == 3
    assert all(j.recipe.style == "serial" for j in jobs)


async def test_pause_and_resume_requests_switch_the_conveyor(tmp_path: Path) -> None:
    studio = _studio(tmp_path, MemoryJobs(), [])
    _drop(tmp_path, "a", {"kind": "pause"})

    assert await studio.sync() is False
    assert (tmp_path / "status.txt").read_text(encoding="utf-8").startswith("Конвейер на паузе.")

    _drop(tmp_path, "b", {"kind": "resume"})
    assert await studio.sync() is True


async def test_a_bad_request_is_answered_and_set_aside(tmp_path: Path) -> None:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "x.json").write_text("{not json", encoding="utf-8")
    _drop(tmp_path, "y", {"kind": "dance"})

    await _studio(tmp_path, MemoryJobs(), []).sync()

    done = tmp_path / "inbox" / "done"
    assert (done / "x.txt").read_text(encoding="utf-8").startswith("error:")
    assert "unknown request kind 'dance'" in (done / "y.txt").read_text(encoding="utf-8")


async def test_the_status_file_shows_jobs_newest_first_and_where_the_video_is(
    tmp_path: Path,
) -> None:
    store = MemoryJobs()
    first, second = Job.new("маяк"), Job.new("лифт")
    second.status, second.script = Status.ASSEMBLED, script(title="Лифт без кнопок")
    await store.add(first)
    await store.add(second)

    await _studio(tmp_path, store, []).sync()

    text = (tmp_path / "status.txt").read_text(encoding="utf-8").splitlines()
    assert text[1].startswith(second.id.hex[:8])
    assert text[2].strip() == f"ролик: reelsmith/videos/{showcase_name(second)}"
    assert text[3].startswith(first.id.hex[:8])


def test_the_showcase_name_is_the_short_id_and_the_title() -> None:
    job = Job.new("идея")
    job.script = script(title="Потоп, выпуск 1: Утро!")

    assert showcase_name(job) == f"{job.id.hex[:8]}-потоп-выпуск-1-утро.mp4"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")
async def test_a_request_from_comfyui_ends_as_a_video_in_the_assets_folder(tmp_path: Path) -> None:
    services = synthetic_services(
        media=tmp_path / "media", outbox=tmp_path / "outbox", styles=REPO_STYLES, tariff=DEFAULT
    )
    showcase = tmp_path / "studio" / "output" / "reelsmith" / "videos"
    services = replace(services, showcase=showcase)
    store = MemoryJobs()
    stages = [replace(s, settled=timedelta(0)) for s in stages_for(services)]
    conveyor = Conveyor(stages, store, services, Gpu({}), batch_size=2, max_attempts=5)
    studio = _studio(tmp_path / "studio", store, [])
    _drop(
        tmp_path / "studio",
        "a",
        {"kind": "video", "story": "Ночная смена в архиве", "style": "noir", "animation": "still"},
    )

    await studio.sync()
    while await conveyor.turn():
        pass
    await studio.sync()

    (job,) = await store.find()
    assert job.status is Status.ASSEMBLED
    assert (showcase / showcase_name(job)).stat().st_size > 0
    assert f"reelsmith/videos/{showcase_name(job)}" in (
        tmp_path / "studio" / "status.txt"
    ).read_text(encoding="utf-8")
