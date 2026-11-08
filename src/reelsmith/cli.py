import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Annotated, NoReturn
from uuid import UUID

import structlog
import typer

from reelsmith import app as build
from reelsmith.beats import BeatScript, read_library
from reelsmith.books import read_book
from reelsmith.models import Job, Metrics, Recipe, StageError, Status
from reelsmith.remix import ideas_file as remix_file
from reelsmith.remix import load as load_library
from reelsmith.remix import remix as make_remix
from reelsmith.report import Arm, Report, compare, report
from reelsmith.series import ideas, outline_markdown, write_serial
from reelsmith.services.ffmpeg import preview
from reelsmith.settings import Settings
from reelsmith.store import PostgresJobs
from reelsmith.styles import Styles

app = typer.Typer(no_args_is_help=True, add_completion=False)

Model = Annotated[str | None, typer.Option(help="model name; the default comes from .env")]
Style = Annotated[str | None, typer.Option(help="style template from the styles folder")]


def _settings() -> Settings:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    return Settings()


def _run[T](settings: Settings, work: Callable[[PostgresJobs], Awaitable[T]]) -> T:
    async def go() -> T:
        async with build.database(settings) as jobs:
            return await work(jobs)

    try:
        return asyncio.run(go())
    except LookupError as exc:
        _fail(str(exc))


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _known_style(settings: Settings, name: str) -> None:
    try:
        Styles(settings.styles).get(name)
    except StageError as exc:
        _fail(str(exc))


def _override(base: Recipe, **chosen: str | int | None) -> Recipe:
    return base.model_copy(update={k: v for k, v in chosen.items() if v is not None})


def _expect(job: Job, status: Status) -> None:
    if job.status is not status:
        _fail(f"job {job.id} is {job.status.value}, not {status.value}")


def _cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    cells = [[_cell(v) for v in row] for row in rows]
    widths = [max([len(h), *(len(r[i]) for r in cells)]) for i, h in enumerate(headers)]

    def line(row: Sequence[str]) -> str:
        return "  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip()

    return "\n".join([line(headers), *map(line, cells)])


def _print_arms(arms: list[Arm]) -> None:
    headers = [
        "arm",
        "videos",
        "good",
        "usd",
        "per video",
        "per good",
        "qa",
        "flagged",
        "rating",
        "ret3s",
    ]
    rows = [
        (
            a.name,
            a.videos,
            a.good,
            a.usd,
            a.cost_per_video,
            a.cost_per_good,
            a.qa_score,
            a.flagged,
            a.rating,
            a.retention_3s,
        )
        for a in arms
    ]
    typer.echo(_table(headers, rows))


def _print_report(made: Report) -> None:
    typer.echo(
        f"videos {made.videos}  good {made.good}  failed {made.failed}  pending {made.pending}"
    )
    typer.echo(
        f"spent ${made.usd:.2f}  cost per good ${_cell(made.cost_per_good)}  "
        f"qa pass rate {_cell(made.qa_pass_rate)}  gpu hours {made.gpu_hours:.2f}"
    )
    headers = ["model", "calls", "flagged", "flag rate", "usd", "gpu hours"]
    rows = [
        (r.provider, r.calls, r.flagged, r.flag_rate, r.usd, r.gpu_hours) for r in made.providers
    ]
    typer.echo(_table(headers, rows))
    if made.hooks:
        hooks = [(h.kind, h.videos, h.retention_3s, h.completion) for h in made.hooks]
        typer.echo(_table(["hook", "videos", "retention 3s", "completion"], hooks))


@app.command()
def migrate(folder: Path = Path("/app/migrations")) -> None:
    """Create or update the jobs table."""
    _run(_settings(), lambda jobs: jobs.migrate(folder))


@app.command()
def add(
    ideas: Annotated[list[str], typer.Argument(help="One or more ideas, e.g. 'зомби в метро'")],
    style: Style = None,
    image: Model = None,
    video: Model = None,
    hook_video: Model = None,
    hook_shots: int | None = None,
    experiment: str | None = None,
    arm: str | None = None,
) -> None:
    """Queue ideas for the conveyor."""
    settings = _settings()
    recipe = _override(
        settings.recipe(),
        style=style,
        image=image,
        video=video,
        hook_video=hook_video,
        hook_shots=hook_shots,
    )
    _known_style(settings, recipe.style)

    async def go(jobs: PostgresJobs) -> None:
        for idea in ideas:
            job = Job.new(idea, recipe, experiment=experiment, arm=arm)
            await jobs.add(job)
            typer.echo(f"{job.id}  {idea}")

    _run(settings, go)


@app.command()
def queue(file: Path, style: Style = None) -> None:
    """Queue every idea in a text file, one per line, and mark the lines as queued.
    `[noir] idea` picks a style for one line; empty lines and lines with # are skipped."""
    settings = _settings()
    lines = file.read_text(encoding="utf-8").splitlines()
    wanted = ideas(lines)
    for _, line_style, _ in wanted:
        _known_style(settings, line_style or style or settings.style)

    async def go(jobs: PostgresJobs) -> None:
        for number, line_style, idea in wanted:
            recipe = _override(settings.recipe(), style=line_style or style)
            job = Job.new(idea, recipe)
            await jobs.add(job)
            lines[number] = f"# {job.id.hex[:8]} {lines[number].strip()}"
            typer.echo(f"{job.id}  {idea}")

    _run(settings, go)
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def series(
    story: Path,
    episodes: Annotated[int, typer.Option(min=1, max=30)] = 10,
    name: str | None = None,
    style: Style = None,
    out: Path = Path("/data/studio/series"),
) -> None:
    """Turn a synopsis, a few sentences or a few hundred words, into a serial: the bible in
    NAME.md and one beat-by-beat episode outline per line in NAME.txt, ready for `queue`."""
    settings = _settings()
    chosen = style or settings.style
    _known_style(settings, chosen)
    synopsis = story.read_text(encoding="utf-8").strip()
    template = Styles(settings.styles).get(chosen)
    try:
        made = asyncio.run(build.serial(settings, synopsis, template, episodes))
    except StageError as exc:
        _fail(str(exc))
    for path in write_serial(made, chosen, out, name or story.stem):
        typer.echo(path)


@app.command()
def adapt(
    book: Path,
    episodes: Annotated[int, typer.Option(min=1, max=30, help="the most, never stretched")] = 5,
    name: str | None = None,
    style: Style = None,
    out: Path = Path("/data/studio/series"),
) -> None:
    """Turn a finished story or a whole book (.txt, .fb2, .epub) into a serial that keeps the
    author's events: the bible in NAME.md and one outline per line in NAME.txt. The story
    takes as many episodes as it has parts, at most --episodes."""
    settings = _settings()
    chosen = style or settings.style
    _known_style(settings, chosen)
    try:
        text = read_book(book)
    except (ValueError, OSError) as exc:
        _fail(str(exc))
    template = Styles(settings.styles).get(chosen)
    try:
        made = asyncio.run(build.adaptation(settings, text, template, episodes, typer.echo))
    except StageError as exc:
        _fail(str(exc))
    for path in write_serial(made, chosen, out, name or book.stem):
        typer.echo(path)


@app.command()
def remix(
    count: Annotated[int, typer.Option(min=1, max=200)] = 12,
    theme: Annotated[list[str] | None, typer.Option(help="e.g. space; repeat for more")] = None,
    seed: int | None = None,
    style: Style = None,
    library: Path | None = None,
    out: Path | None = None,
) -> None:
    """Short ideas recombined from the structure library: a world, a hero, a goal, two
    obstacles with their tricks, an ally, a reversal, a hook. Same seed, same ideas."""
    settings = _settings()
    chosen = style or settings.style
    _known_style(settings, chosen)
    parts = load_library(library or settings.studio / "structures.toml")
    used = seed if seed is not None else random.randrange(1_000_000)
    try:
        made = make_remix(parts, count, seed=used, themes=theme)
    except ValueError as exc:
        _fail(str(exc))
    target = out or settings.studio / "ideas" / f"remix-{used}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(remix_file(made, parts, chosen, used), encoding="utf-8")
    typer.echo(f"{target}  ({len(made)} ideas, seed {used})")


@app.command()
def beats(
    file: Path,
    series: Annotated[Path, typer.Option(help="the series folder with library.toml")],
    style: Annotated[str, typer.Option(help="style template for the brief")] = "rules-beats",
    out: Path | None = None,
) -> None:
    """A beat script for every idea in a file, sent back to the writer until the code finds
    nothing or the rewrites are spent. Nothing is rendered: this shows how well the writer
    model keeps the beat format. One JSON per idea goes to OUT, by default SERIES/scripts."""
    settings = _settings()
    _known_style(settings, style)
    try:
        library = read_library(series)
    except StageError as exc:
        _fail(str(exc))
    found = ideas(file.read_text(encoding="utf-8").splitlines())
    if not found:
        _fail(f"no ideas in {file}")
    target = out or series / "scripts"
    target.mkdir(parents=True, exist_ok=True)

    def done(n: int, script: BeatScript, rewrites: int, left: list[str]) -> None:
        path = target / f"{file.stem}-{n:02d}.json"
        path.write_text(script.model_dump_json(indent=1), encoding="utf-8")
        verdict = "ok" if not left else f"{len(left)} problem(s) left: {' '.join(left)}"
        typer.echo(f"{path}  rewrites {rewrites}  {verdict}")

    template = Styles(settings.styles).get(style)
    try:
        made = asyncio.run(
            build.beat_scripts(settings, [i for _, _, i in found], template, library, done)
        )
    except StageError as exc:
        _fail(str(exc))
    passed = sum(1 for _, _, left in made if not left)
    average = sum(r for _, r, _ in made) / len(made)
    typer.echo(f"passed {passed} of {len(made)}, {average:.1f} rewrites on average")


@app.command()
def outline(file: Path, style: Style = None, out: Path | None = None) -> None:
    """The model's outline for every idea in a file, without rendering: to read the plots
    before spending GPU time on them, or to compare with outlines written by hand."""
    settings = _settings()
    chosen = style or settings.style
    _known_style(settings, chosen)
    found = ideas(file.read_text(encoding="utf-8").splitlines())
    if not found:
        _fail(f"no ideas in {file}")
    template = Styles(settings.styles).get(found[0][1] or chosen)
    try:
        planned = asyncio.run(build.outlines(settings, [idea for _, _, idea in found], template))
    except StageError as exc:
        _fail(str(exc))
    sections = [
        f"## {n}. {idea}\n\n{outline_markdown(made)}"
        for n, ((_, _, idea), made) in enumerate(zip(found, planned, strict=True), 1)
    ]
    target = out or file.with_suffix(".outlines.md")
    target.write_text(
        f"# Outlines by the model for {file.name}\n\n" + "\n".join(sections), encoding="utf-8"
    )
    typer.echo(target)


@app.command()
def fork(
    job_id: UUID,
    arm: str = "B",
    style: Style = None,
    image: Model = None,
    video: Model = None,
    hook_video: Model = None,
    hook_shots: int | None = None,
) -> None:
    """Another arm on the same script, voices and frames. The parent becomes arm A.
    A different style here changes only captions, motion wording and judging."""

    async def go(jobs: PostgresJobs) -> None:
        parent = await jobs.get(job_id)
        recipe = _override(
            parent.recipe,
            style=style,
            image=image,
            video=video,
            hook_video=hook_video,
            hook_shots=hook_shots,
        )
        child = parent.fork(recipe, arm)
        await jobs.save(parent)
        await jobs.add(child)
        typer.echo(f"{child.id}  arm {arm} of experiment {child.experiment}")

    _run(_settings(), go)


@app.command()
def approve(job_id: UUID) -> None:
    """Let an assembled video go to publishing."""

    async def go(jobs: PostgresJobs) -> None:
        job = await jobs.get(job_id)
        _expect(job, Status.ASSEMBLED)
        job.status = Status.APPROVED
        await jobs.save(job)

    _run(_settings(), go)


@app.command()
def reject(job_id: UUID, reason: str = "rejected by hand") -> None:
    """Send an assembled video back: its clips are animated again with new seeds."""
    settings = _settings()

    async def go(jobs: PostgresJobs) -> None:
        job = await jobs.get(job_id)
        _expect(job, Status.ASSEMBLED)
        job.reject(reason, settings.max_attempts)
        await jobs.save(job)
        typer.echo(f"{job.id}  {job.status.value}  attempt {job.attempts}")

    _run(settings, go)


@app.command()
def rate(job_id: UUID, score: Annotated[int, typer.Argument(min=1, max=10)]) -> None:
    """Blind rating of a cut, 1 to 10. Shows up in `compare`."""

    async def go(jobs: PostgresJobs) -> None:
        job = await jobs.get(job_id)
        job.rating = score
        await jobs.save(job)

    _run(_settings(), go)


@app.command()
def measure(
    job_id: UUID,
    views: int = typer.Option(..., min=0),
    retention_3s: float = typer.Option(..., min=0, max=1),
    completion: float = typer.Option(..., min=0, max=1),
) -> None:
    """Enter the platform's numbers for a published video."""

    async def go(jobs: PostgresJobs) -> None:
        job = await jobs.get(job_id)
        _expect(job, Status.PUBLISHED)
        job.metrics = Metrics(views=views, retention_3s=retention_3s, completion=completion)
        job.status = Status.MEASURED
        await jobs.save(job)

    _run(_settings(), go)


@app.command(name="compare")
def compare_arms(experiment: str) -> None:
    """Arms of one experiment side by side."""
    arms = _run(_settings(), lambda jobs: jobs.find(experiment=experiment))
    if not arms:
        _fail(f"no jobs in experiment {experiment!r}")
    _print_arms(compare(arms))


@app.command(name="report")
def report_all() -> None:
    """Cost per good video, flags per model, retention per hook, GPU hours."""
    settings = _settings()
    jobs = _run(settings, lambda store: store.find())
    _print_report(report(jobs, settings.tariff(), qa_pass=settings.qa_pass))


@app.command()
def status() -> None:
    """How many jobs sit at each stage."""
    for name, count in sorted(_run(_settings(), lambda jobs: jobs.summary()).items()):
        typer.echo(f"{name:<10} {count}")


@app.command(name="jobs")
def list_jobs(
    status: Annotated[str | None, typer.Option(help="only this status, e.g. assembled")] = None,
) -> None:
    """Every job: id, status, attempts, QA score, cost, style, idea and the last error."""
    wanted = _status(status) if status is not None else None
    found = _run(_settings(), lambda jobs: jobs.find(status=wanted))
    rows = [
        (
            str(job.id), job.status.value, job.attempts, job.qa.score if job.qa else None,
            job.cost, job.recipe.style, _clip(job.idea, 40), _clip(job.last_error or "", 60),
        )
        for job in found
    ]  # fmt: skip
    headers = ["id", "status", "tries", "qa", "usd", "style", "idea", "last error"]
    typer.echo(_table(headers, rows))


def _status(name: str) -> Status:
    try:
        return Status(name)
    except ValueError:
        _fail(f"no status {name!r}; have: {', '.join(s.value for s in Status)}")


@app.command()
def retry(
    job_id: UUID,
    status: Annotated[str | None, typer.Option(help="resume from this status, e.g. framed")] = None,
) -> None:
    """Put a failed or stuck job back to work: attempts start over and its lease is dropped.
    Everything it has made so far is kept, so `--status framed` redoes only missing clips."""
    wanted = _status(status) if status is not None else None

    async def go(jobs: PostgresJobs) -> None:
        job = await jobs.get(job_id)
        if wanted is None and job.status is Status.FAILED:
            _fail("a failed job needs --status, e.g. --status framed")
        job.status = wanted or job.status
        job.attempts, job.last_error = 0, None
        await jobs.save(job)
        typer.echo(f"{job.id}  {job.status.value}")

    _run(_settings(), go)


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


@app.command()
def work(
    once: bool = False,
    stages: Annotated[str | None, typer.Option(help="comma-separated, e.g. voice,paint")] = None,
) -> None:
    """Run the conveyor. With --once, make a single pass and exit."""
    settings = _settings()
    chosen = stages.split(",") if stages else None

    async def go() -> None:
        async with build.application(settings, stage_names=chosen) as built:
            await built.run(settings.idle_seconds, once=once)

    asyncio.run(go())


@app.command()
def smoke(out: Path = Path("/data/studio/smoke")) -> None:
    """One call to every model on this machine, with timings: run it on a fresh GPU box."""
    settings = _settings()
    out.mkdir(parents=True, exist_ok=True)
    checks = asyncio.run(build.smoke(settings, out))
    typer.echo(
        _table(
            ["step", "ok", "seconds", "result"],
            [(c.name, "yes" if c.ok else "NO", c.seconds, c.result[:90]) for c in checks],
        )
    )
    typer.echo(f"files: {out}")
    if not all(c.ok for c in checks):
        raise typer.Exit(1)


@app.command(name="styles")
def list_styles() -> None:
    """The style templates in the styles folder, with what each one is for."""
    folder = Styles(_settings().styles)
    for name in folder.names():
        typer.echo(f"{name:<16} {folder.get(name).about}")


@app.command(name="preview")
def preview_style(name: str, out: Path = Path("preview")) -> None:
    """Draws the captions and every overlay of a style on a dark frame. No models needed."""
    settings = _settings()
    _known_style(settings, name)
    out.mkdir(parents=True, exist_ok=True)
    typer.echo(asyncio.run(preview(Styles(settings.styles).get(name), out / f"{name}.png")))


@app.command(name="demo")
def run_demo(
    ideas: Annotated[int, typer.Option(min=1)] = 3,
    arm_a: str = "wan-2.2",
    arm_b: str = "wan-5b",
    style: Style = None,
    out: Path = Path("demo"),
) -> None:
    """The whole conveyor on synthetic models, with an A/B fork, in memory."""
    settings = _settings()
    recipe = _override(settings.recipe(), style=style)
    chosen = [build.DEMO_IDEAS[i % len(build.DEMO_IDEAS)] for i in range(ideas)]
    try:
        result = asyncio.run(
            build.demo(
                chosen,
                arm_a=recipe.model_copy(update={"video": arm_a}),
                arm_b=recipe.model_copy(update={"video": arm_b}),
                out=out,
                styles=settings.styles,
                tariff=settings.tariff(),
            )
        )
    except StageError as exc:
        _fail(str(exc))
    for job in result.jobs:
        typer.echo(f"{job.id}  {job.arm}  {job.status.value:<9}  {job.idea}")
    typer.echo(f"ratings are synthetic; finished videos are under {out / 'outbox'}\n")
    _print_arms(result.arms)
    typer.echo()
    _print_report(result.report)
