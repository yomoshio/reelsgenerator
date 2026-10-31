import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reelsmith import app as build
from reelsmith import cli
from reelsmith.models import Status
from reelsmith.settings import Settings
from reelsmith.store import MemoryJobs
from tests.fakes import script

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")
runner = CliRunner()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> MemoryJobs:
    jobs = MemoryJobs()

    @asynccontextmanager
    async def fake_database(settings: Settings) -> AsyncIterator[MemoryJobs]:
        yield jobs

    monkeypatch.setattr(build, "database", fake_database)
    return jobs


def test_add_and_fork_set_recipe_and_experiment(store: MemoryJobs) -> None:
    added = runner.invoke(
        cli.app, ["add", "зомби в метро", "--video", "wan-5b", "--hook-video", "wan-2.2"]
    )
    assert added.exit_code == 0, added.output
    (parent,) = asyncio.run(store.find())
    assert (parent.recipe.video, parent.recipe.hook_video, parent.recipe.image) == (
        "wan-5b",
        "wan-2.2",
        "z-image",
    )

    forked = runner.invoke(cli.app, ["fork", str(parent.id), "--video", "wan-2.2", "--arm", "B"])
    assert forked.exit_code == 0, forked.output
    parent, child = asyncio.run(store.find())
    assert (parent.arm, child.arm, child.parent) == ("A", "B", parent.id)
    assert (child.recipe.video, child.recipe.hook_video) == ("wan-2.2", "wan-2.2")
    assert child.experiment == str(parent.id)


def test_approve_reject_rate_and_measure_check_the_status(store: MemoryJobs) -> None:
    runner.invoke(cli.app, ["add", "маяк"])
    (job,) = asyncio.run(store.find())
    job.script = script()
    job.assets.clips = {0: "clips/00.mp4"}

    assert runner.invoke(cli.app, ["approve", str(job.id)]).exit_code == 1
    job.status = Status.ASSEMBLED
    assert runner.invoke(cli.app, ["reject", str(job.id), "--reason", "flat"]).exit_code == 0
    assert (job.status, job.assets.clips, job.last_error) == (Status.FRAMED, {}, "flat")

    job.status = Status.ASSEMBLED
    assert runner.invoke(cli.app, ["approve", str(job.id)]).exit_code == 0
    assert job.status is Status.APPROVED
    assert runner.invoke(cli.app, ["rate", str(job.id), "8"]).exit_code == 0
    assert job.rating == 8

    job.status = Status.PUBLISHED
    measured = runner.invoke(
        cli.app,
        ["measure", str(job.id), "--views", "1200", "--retention-3s", "0.6", "--completion", "0.3"],
    )
    assert measured.exit_code == 0, measured.output
    assert job.status is Status.MEASURED
    assert job.metrics is not None
    assert job.metrics.views == 1200


def test_compare_and_report_print_tables(store: MemoryJobs) -> None:
    runner.invoke(cli.app, ["add", "маяк", "--experiment", "x", "--arm", "A"])
    runner.invoke(cli.app, ["add", "маяк", "--experiment", "x", "--arm", "B"])

    compared = runner.invoke(cli.app, ["compare", "x"])
    reported = runner.invoke(cli.app, ["report"])
    missing = runner.invoke(cli.app, ["compare", "nothing"])

    assert compared.exit_code == 0, compared.output
    assert compared.output.splitlines()[0].split() == [
        "arm", "videos", "good", "usd", "per", "video", "per", "good", "qa", "flagged", "rating", "ret3s"
    ]  # fmt: skip
    assert [line.split()[0] for line in compared.output.splitlines()[1:]] == ["A", "B"]
    assert "cost per good $-" in reported.output
    assert missing.exit_code == 1


def test_unknown_job_is_reported_not_raised(store: MemoryJobs) -> None:
    result = runner.invoke(cli.app, ["approve", "00000000-0000-0000-0000-000000000000"])

    assert result.exit_code == 1
    assert "no job" in result.output


@needs_ffmpeg
def test_demo_prints_both_arms_and_the_report(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["demo", "--ideas", "1", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("A ") for line in lines)
    assert any(line.startswith("B ") for line in lines)
    assert "cost per good" in result.output
    assert (tmp_path / "outbox").is_dir()
