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
from reelsmith.services import synthetic
from reelsmith.settings import Settings
from reelsmith.store import MemoryJobs
from tests.fakes import REPO_STYLES, script

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")
runner = CliRunner()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> MemoryJobs:
    jobs = MemoryJobs()

    @asynccontextmanager
    async def fake_database(settings: Settings) -> AsyncIterator[MemoryJobs]:
        yield jobs

    monkeypatch.setattr(build, "database", fake_database)
    monkeypatch.setenv("REELSMITH_STYLES", str(REPO_STYLES))
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
def test_demo_prints_both_arms_and_the_report(tmp_path: Path, store: MemoryJobs) -> None:
    result = runner.invoke(cli.app, ["demo", "--ideas", "1", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("A ") for line in lines)
    assert any(line.startswith("B ") for line in lines)
    assert "cost per good" in result.output
    assert (tmp_path / "outbox").is_dir()


def test_add_takes_a_style_and_refuses_an_unknown_one(store: MemoryJobs) -> None:
    ok = runner.invoke(cli.app, ["add", "маяк", "--style", "rules-serial"])
    bad = runner.invoke(cli.app, ["add", "маяк", "--style", "nope"])

    assert ok.exit_code == 0, ok.output
    assert bad.exit_code == 1
    assert "no style named 'nope'" in bad.output
    (job,) = asyncio.run(store.find())
    assert job.recipe.style == "rules-serial"


def test_fork_with_another_style_keeps_the_script(store: MemoryJobs) -> None:
    runner.invoke(cli.app, ["add", "маяк"])
    (parent,) = asyncio.run(store.find())
    parent.script = script()
    runner.invoke(cli.app, ["fork", str(parent.id), "--style", "rules-serial"])

    parent, child = asyncio.run(store.find())
    assert (parent.recipe.style, child.recipe.style) == ("noir", "rules-serial")


def test_jobs_lists_ids_and_filters_by_status(store: MemoryJobs) -> None:
    runner.invoke(
        cli.app, ["add", "маяк", "лифт без кнопки первого этажа и без выхода наружу совсем"]
    )
    first, second = asyncio.run(store.find())
    second.status = Status.FAILED
    second.last_error = "comfy: prompt did not finish"
    asyncio.run(store.save(second))

    everything = runner.invoke(cli.app, ["jobs"])
    failed = runner.invoke(cli.app, ["jobs", "--status", "failed"])
    wrong = runner.invoke(cli.app, ["jobs", "--status", "nope"])

    assert everything.exit_code == 0, everything.output
    assert str(first.id) in everything.output
    assert "лифт без кнопки первого этажа и без вых…" in everything.output
    assert str(first.id) not in failed.output
    assert "comfy: prompt did not finish" in failed.output
    assert wrong.exit_code == 1
    assert "no status 'nope'" in wrong.output


def test_ideas_skips_comments_and_reads_a_style_prefix() -> None:
    lines = [
        "# мои идеи",
        "",
        "маяк, который зажигается сам",
        "  [noir] лифт без кнопки  ",
        "[rules-serial]",
    ]

    assert cli.ideas(lines) == [
        (2, None, "маяк, который зажигается сам"),
        (3, "noir", "лифт без кнопки"),
    ]


def test_queue_adds_each_idea_and_marks_its_line(store: MemoryJobs, tmp_path: Path) -> None:
    file = tmp_path / "ideas.txt"
    file.write_text("# идеи\nмаяк\n[rules-serial] Часть 1. Метро\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["queue", str(file)])

    assert result.exit_code == 0, result.output
    jobs = {j.idea: j for j in asyncio.run(store.find())}
    assert (jobs["маяк"].recipe.style, jobs["Часть 1. Метро"].recipe.style) == (
        "noir",
        "rules-serial",
    )
    marked = file.read_text(encoding="utf-8").splitlines()
    assert marked[0] == "# идеи"
    assert marked[1] == f"# {jobs['маяк'].id.hex[:8]} маяк"
    assert cli.ideas(marked) == []


def test_queue_refuses_an_unknown_style_before_adding_anything(
    store: MemoryJobs, tmp_path: Path
) -> None:
    file = tmp_path / "ideas.txt"
    file.write_text("маяк\n[nope] лифт\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["queue", str(file)])

    assert result.exit_code == 1
    assert asyncio.run(store.find()) == []
    assert file.read_text(encoding="utf-8") == "маяк\n[nope] лифт\n"


def test_retry_resumes_a_failed_job_from_a_chosen_status(store: MemoryJobs) -> None:
    runner.invoke(cli.app, ["add", "маяк"])
    (job,) = asyncio.run(store.find())
    job.status, job.attempts, job.last_error = Status.FAILED, 5, "clips flagged"
    asyncio.run(store.save(job))

    refused = runner.invoke(cli.app, ["retry", str(job.id)])
    resumed = runner.invoke(cli.app, ["retry", str(job.id), "--status", "framed"])

    assert refused.exit_code == 1
    assert "needs --status" in refused.output
    assert resumed.exit_code == 0, resumed.output
    (job,) = asyncio.run(store.find())
    assert (job.status, job.attempts, job.last_error) == (Status.FRAMED, 0, None)


def test_styles_lists_what_each_is_for(store: MemoryJobs) -> None:
    result = runner.invoke(cli.app, ["styles"])

    assert result.exit_code == 0, result.output
    assert "noir" in result.output
    assert "rules-serial" in result.output
    assert "numbered rules" in result.output


@needs_ffmpeg
def test_preview_draws_one_frame_with_every_overlay(tmp_path: Path, store: MemoryJobs) -> None:
    result = runner.invoke(cli.app, ["preview", "rules-serial", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    frame = tmp_path / "rules-serial.png"
    assert frame.stat().st_size > 5_000
    ass = (tmp_path / "rules-serial.ass").read_text(encoding="utf-8")
    assert ass.count("Dialogue: 1,") == 5


@needs_ffmpeg
def test_demo_stops_early_on_an_unknown_style(tmp_path: Path, store: MemoryJobs) -> None:
    result = runner.invoke(
        cli.app, ["demo", "--ideas", "1", "--style", "nope", "--out", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "no style named 'nope'" in result.output


def test_series_writes_a_bible_and_an_ideas_file(
    store: MemoryJobs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REELSMITH_SERVICES", "synthetic")
    story = tmp_path / "flood.txt"
    story.write_text("Ночью прорвало дамбу, вода поднимается по этажу в час.", encoding="utf-8")

    result = runner.invoke(
        cli.app, ["series", str(story), "--episodes", "3", "--out", str(tmp_path / "out")]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "flood.md").exists()
    assert (
        len(cli.ideas((tmp_path / "out" / "flood.txt").read_text(encoding="utf-8").splitlines()))
        == 3
    )


def test_remix_writes_ideas_for_a_theme(
    store: MemoryJobs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REELSMITH_STUDIO", str(Path(__file__).parent.parent / "studio"))
    out = tmp_path / "remix.txt"

    result = runner.invoke(
        cli.app, ["remix", "--count", "3", "--theme", "zombie", "--seed", "4", "--out", str(out)]
    )

    assert result.exit_code == 0, result.output
    assert len(cli.ideas(out.read_text(encoding="utf-8").splitlines())) == 3


def test_outline_writes_the_models_plan_for_every_idea(
    store: MemoryJobs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REELSMITH_SERVICES", "synthetic")
    file = tmp_path / "batch.txt"
    file.write_text(
        "# идеи\nстанция теряет воздух\n[noir] ночная смена в архиве\n", encoding="utf-8"
    )

    result = runner.invoke(cli.app, ["outline", str(file)])

    assert result.exit_code == 0, result.output
    text = (tmp_path / "batch.outlines.md").read_text(encoding="utf-8")
    assert "## 1. станция теряет воздух" in text
    assert "## 2. ночная смена в архиве" in text
    assert "Detail planted early:" in text


@needs_ffmpeg
def test_smoke_runs_every_model_once_and_reports_each(
    store: MemoryJobs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REELSMITH_SERVICES", "synthetic")

    result = runner.invoke(cli.app, ["smoke", "--out", str(tmp_path / "smoke")])

    assert result.exit_code == 0, result.output
    steps = [line.split()[0] for line in result.output.splitlines()[1:7]]
    assert steps == ["plan", "voice", "subtitles", "frame", "clip", "music"]
    assert (tmp_path / "smoke" / "clip.mp4").exists()


@needs_ffmpeg
def test_smoke_skips_what_depends_on_a_failed_step_and_fails(
    store: MemoryJobs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REELSMITH_SERVICES", "synthetic")

    async def broken(*_: object, **__: object) -> Path:
        raise RuntimeError("no such model")

    monkeypatch.setattr(synthetic.SyntheticPainter, "paint", broken)

    result = runner.invoke(cli.app, ["smoke", "--out", str(tmp_path / "smoke")])

    assert result.exit_code == 1
    assert "RuntimeError: no such model" in result.output
    assert " clip " not in result.output
