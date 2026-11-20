from pathlib import Path

import pytest

from reelsmith.jobs import Context, Job, JobError, Jobs, Source, Stage, Status, run_once
from reelsmith.llm import Llm
from reelsmith.settings import Settings
from reelsmith.styles import Styles


def _ctx(tmp_path: Path, tries: int = 3) -> Context:
    settings = Settings(jobs=tmp_path / "jobs", tries=tries)
    return Context(settings, Llm("http://nowhere/v1"), Styles(tmp_path))


def test_create_writes_the_folder_the_source_and_the_status(tmp_path: Path) -> None:
    jobs = Jobs(tmp_path)
    job = jobs.create(Source(kind="idea", text="Вода по колено"), "blackout")
    folder = jobs.folder(job)
    assert (folder / "source.txt").read_text(encoding="utf-8") == "Вода по колено"
    assert jobs.get(job.id[:6]).status == Status.NEW


def test_get_needs_exactly_one_match(tmp_path: Path) -> None:
    jobs = Jobs(tmp_path)
    jobs.create(Source(kind="idea", text="a"), "blackout")
    jobs.create(Source(kind="idea", text="b"), "blackout")
    with pytest.raises(JobError, match="2 jobs"):
        jobs.get(jobs.all()[0].id[:4])
    with pytest.raises(JobError, match="no job"):
        jobs.get("zzzz")


async def test_a_failing_step_keeps_the_status_and_records_the_error(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    jobs = Jobs(ctx.settings.jobs)
    first = jobs.create(Source(kind="idea", text="a"), "blackout")
    second = jobs.create(Source(kind="idea", text="b"), "blackout")

    async def write(job: Job, folder: Path, ctx: Context) -> None:
        if job.id == first.id:
            raise ConnectionError("box unreachable")

    advanced = await run_once(jobs, ctx, [Stage("write", Status.NEW, Status.WRITTEN, write)])
    assert advanced == 1
    stuck = jobs.get(first.id)
    assert stuck.status == Status.NEW
    assert stuck.error == "write: box unreachable"
    assert stuck.tries == 1
    assert jobs.get(second.id).status == Status.WRITTEN


async def test_the_last_try_fails_the_job(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, tries=2)
    jobs = Jobs(ctx.settings.jobs)
    job = jobs.create(Source(kind="idea", text="a"), "blackout")

    async def broken(job: Job, folder: Path, ctx: Context) -> None:
        raise ValueError("no")

    stages = [Stage("write", Status.NEW, Status.WRITTEN, broken)]
    await run_once(jobs, ctx, stages)
    await run_once(jobs, ctx, stages)
    assert jobs.get(job.id).status == Status.FAILED


async def test_a_job_goes_through_every_stage_in_one_pass(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    jobs = Jobs(ctx.settings.jobs)
    job = jobs.create(Source(kind="idea", text="a"), "blackout")

    async def step(job: Job, folder: Path, ctx: Context) -> None:
        return None

    stages = [
        Stage("write", Status.NEW, Status.WRITTEN, step),
        Stage("voice", Status.WRITTEN, Status.VOICED, step),
    ]
    assert await run_once(jobs, ctx, stages) == 2
    done = jobs.get(job.id)
    assert done.status == Status.VOICED
    assert [e.step for e in done.log] == ["write", "voice"]


def test_a_job_sent_back_loses_the_work_of_later_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reelsmith import cli

    monkeypatch.setenv("REELSMITH_JOBS", str(tmp_path))
    jobs = Jobs(tmp_path)
    job = jobs.create(Source(kind="idea", text="x"), "blackout")
    folder = jobs.folder(job)
    for name in ("plan.json", "episode.json", "final.mp4"):
        (folder / name).write_text("x")
    for name in ("voice", "scenes", "keys", "clips"):
        (folder / name).mkdir()
        (folder / name / "beat01").write_text("x")
    cli.retry(job.id, Status.VOICED)
    assert sorted(p.name for p in folder.iterdir()) == [
        "episode.json", "job.json", "plan.json", "source.txt", "voice",
    ]  # fmt: skip
