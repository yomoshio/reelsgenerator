"""The `reelsmith` command. Every command works on the job folders in REELSMITH_JOBS."""

import asyncio
import json
import logging
import re
import shutil
import time
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import structlog
import typer
from PIL import Image
from pydantic import BaseModel

from reelsmith.books import BOOKS, episodes, read_book
from reelsmith.captions import Word
from reelsmith.jobs import Context, Job, JobError, Jobs, Source, Status, run_once
from reelsmith.llm import Llm
from reelsmith.runtime import Report, catalog, keys, scene_input
from reelsmith.scenes import fallback
from reelsmith.settings import Settings
from reelsmith.stages import stages
from reelsmith.story import Card, Episode
from reelsmith.styles import StyleError, Styles
from reelsmith.voice import Speech

app = typer.Typer(no_args_is_help=True, add_completion=False)
IDEA_WORDS = 80  # a source this short is an idea to invent a story from, longer is a story
GOLDEN = Path(__file__).parents[2] / "tests" / "data" / "flood-01.json"


def _settings() -> Settings:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    return Settings()


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _job(jobs: Jobs, prefix: str) -> Job:
    try:
        return jobs.get(prefix)
    except JobError as exc:
        _fail(str(exc))


@app.command()
def add(
    text: Annotated[str | None, typer.Argument(help="an idea or a whole story")] = None,
    file: Annotated[Path | None, typer.Option(help=f"a story or book: {', '.join(BOOKS)}")] = None,
    style: Annotated[str | None, typer.Option(help="a style folder in styles/")] = None,
) -> None:
    """Puts an idea, a story or a book in the queue. A long story or a book is retold and
    split into episodes first, one job each; that needs the models."""
    settings = _settings()
    chosen = style or settings.style
    try:
        look = Styles(settings.styles).get(chosen)
    except StyleError as exc:
        _fail(str(exc))
    if file is not None:
        body, title = read_book(file), file.stem
    elif text:
        body, title = text, ""
    else:
        _fail("give an idea, or a file with --file")
    jobs = Jobs(settings.jobs)
    if len(body.split()) < IDEA_WORDS:
        sources = [Source(kind="idea", text=body, title=title)]
    else:

        async def split() -> list[Source]:
            llm = Llm(settings.llm_url, temperature=settings.temperature)
            try:
                return await episodes(
                    Context(settings, llm, Styles(settings.styles)), look, body, title
                )
            finally:
                await llm.close()

        sources = asyncio.run(split())
    for source in sources:
        job = jobs.create(source, chosen)
        typer.echo(f"{job.id}  {source.kind}  {chosen}  {source.title}")


@app.command()
def run(once: Annotated[bool, typer.Option(help="one pass over the stages")] = False) -> None:
    """Moves every job through the stages until nothing is left to do."""
    settings = _settings()

    async def go() -> None:
        llm = Llm(settings.llm_url, temperature=settings.temperature)
        speech = Speech(settings.speech_url)
        ctx = Context(settings, llm, Styles(settings.styles), speech)
        ctx.catalog = lambda: catalog(settings)
        jobs = Jobs(settings.jobs)
        try:
            while await run_once(jobs, ctx, stages()) and not once:
                pass
        finally:
            await llm.close()
            await speech.close()

    asyncio.run(go())
    _print(Jobs(settings.jobs).all())


@app.command(name="jobs")
def list_jobs(status: Annotated[Status | None, typer.Option()] = None) -> None:
    """Jobs with their status, oldest first."""
    found = Jobs(_settings().jobs).all()
    _print([j for j in found if status is None or j.status == status])


def _print(found: list[Job]) -> None:
    for job in found:
        title = job.source.title or job.source.text.splitlines()[0][:50]
        error = f"  ! {job.error}" if job.error else ""
        typer.echo(f"{job.id}  {job.status:<9}  {job.style:<10}  {title}{error}")


@app.command()
def show(job_id: str) -> None:
    """Everything known about one job: status, folder, log."""
    jobs = Jobs(_settings().jobs)
    job = _job(jobs, job_id)
    typer.echo(f"{job.id}  {job.status}  {job.style}  {jobs.folder(job)}")
    if job.error:
        typer.echo(f"error: {job.error} (try {job.tries})")
    for entry in job.log:
        model = f"  {entry.model}" if entry.model else ""
        note = f"  {entry.note}" if entry.note else ""
        typer.echo(f"  {entry.at:%m-%d %H:%M}  {entry.step:<9}{entry.seconds:7.1f} s{model}{note}")


@app.command()
def approve(job_id: str) -> None:
    """Copies the finished video and its post text to the outbox."""
    settings = _settings()
    jobs = Jobs(settings.jobs)
    job = _job(jobs, job_id)
    final = jobs.folder(job) / "final.mp4"
    if job.status != Status.ASSEMBLED or not final.is_file():
        _fail(f"{job.id} is {job.status}; only an assembled job can be approved")
    settings.outbox.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now(UTC):%Y%m%d}-{_slug(job.source.title or job.id)}"
    shutil.copyfile(final, settings.outbox / f"{name}.mp4")
    post = jobs.folder(job) / "post.txt"
    if post.is_file():
        shutil.copyfile(post, settings.outbox / f"{name}.txt")
    job.status = Status.APPROVED
    jobs.save(job)
    typer.echo(settings.outbox / f"{name}.mp4")


@app.command()
def reject(job_id: str, reason: Annotated[str, typer.Option(help="what is wrong")]) -> None:
    """Marks a video as not good enough, with the reason kept in the job's notes."""
    jobs = Jobs(_settings().jobs)
    job = _job(jobs, job_id)
    job.status = Status.REJECTED
    job.notes += f"{datetime.now(UTC):%m-%d %H:%M} rejected: {reason}\n"
    jobs.save(job)


@app.command()
def retry(
    job_id: str,
    status: Annotated[Status | None, typer.Option(help="go back to this status")] = None,
) -> None:
    """Clears the error of a job, or sends it back to an earlier status."""
    jobs = Jobs(_settings().jobs)
    job = _job(jobs, job_id)
    job.error, job.tries = None, 0
    if status is not None:
        job.status = status
    elif job.status == Status.FAILED:
        job.status = job.failed_at or Status.NEW
    jobs.save(job)
    typer.echo(f"{job.id}  {job.status}")


@app.command()
def storyboard(job_id: str) -> None:
    """The middle keyframe of every beat on one sheet, storyboard.jpg in the job's folder."""
    jobs = Jobs(_settings().jobs)
    job = _job(jobs, job_id)
    folder = jobs.folder(job)
    keys = sorted((folder / "keys").glob("beat*-1.png"))
    if not keys:
        _fail(f"{job.id} has no keyframes yet; it is {job.status}")
    thumbs = [Image.open(k).convert("RGB").resize((270, 480)) for k in keys]
    rows = (len(thumbs) + 5) // 6
    sheet = Image.new("RGB", (270 * min(len(thumbs), 6), 480 * rows))
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % 6) * 270, (i // 6) * 480))
    sheet.save(folder / "storyboard.jpg", quality=85)
    typer.echo(folder / "storyboard.jpg")


@app.command()
def redo(
    job_id: str,
    beat: Annotated[int, typer.Option(min=1, help="which beat, from 1")],
    note: Annotated[str, typer.Option(help="what is wrong with it, for the coder")] = "",
) -> None:
    """Sends one beat back to the coder with a note; the video is drawn again after it."""
    jobs = Jobs(_settings().jobs)
    job = _job(jobs, job_id)
    scenes_dir = jobs.folder(job) / "scenes"
    if not (scenes_dir / f"beat{beat:02d}.js").is_file():
        _fail(f"{job.id} has no scene for beat {beat}")
    notes_file = scenes_dir / "notes.json"
    notes = json.loads(notes_file.read_text(encoding="utf-8")) if notes_file.is_file() else {}
    notes[str(beat)] = note or "Draw this beat again, better."
    notes_file.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
    job.status, job.error, job.tries = Status.VOICED, None, 0
    jobs.save(job)
    typer.echo(f"{job.id}  beat {beat} goes back to the coder")


@app.command()
def smoke() -> None:
    """One call to every model and one keyframe drawn, each with its time: is the box ready?"""
    settings = _settings()

    async def go() -> list[tuple[str, float, str]]:
        llm = Llm(settings.llm_url, temperature=0)
        speech = Speech(settings.speech_url)
        results: list[tuple[str, float, str]] = []

        async def timed(name: str, call: Awaitable[str]) -> None:
            started = time.monotonic()
            try:
                note = await call
            except Exception as exc:
                note = f"FAILED: {exc}"
            results.append((name, time.monotonic() - started, note))

        async def planner() -> str:
            got = await llm.json(settings.planner, "Answer with JSON.", "Name a colour.", Smoke)
            return got.word

        async def coder() -> str:
            return (await llm.code(settings.coder, "Answer with a js block.", "function f() {}"))[
                :40
            ]

        async def speak() -> str:
            take = await speech.speak("Свет гаснет. Совсем.", "narrator", settings.language)
            heard = await speech.words(take, settings.language, "Свет гаснет. Совсем.")
            return " ".join(w.text for w in heard)

        async def draw() -> str:
            report = await keyframe(settings)
            return report.error or f"{len(report.pngs)} keyframe(s)"

        async def vision() -> str:
            report = await keyframe(settings)
            seen = await llm.json(
                settings.vision, "Answer with JSON.", "Describe the picture in one word.",
                Smoke, images=report.pngs[:1],
            )  # fmt: skip
            return seen.word

        try:
            for name, call in [("planner", planner()), ("coder", coder()), ("vision", vision()),
                               ("speech", speak()), ("runtime", draw())]:  # fmt: skip
                await timed(name, call)
        finally:
            await llm.close()
            await speech.close()
        return results

    failed = False
    for name, seconds, note in asyncio.run(go()):
        failed |= note.startswith("FAILED")
        typer.echo(f"{name:<8} {seconds:6.1f} s  {note}")
    if failed:
        raise typer.Exit(1)


class Smoke(BaseModel):
    word: str


async def keyframe(settings: Settings) -> Report:
    """One keyframe of the golden episode's first beat, drawn by the plain scene."""
    ep = Episode.model_validate_json(GOLDEN.read_text(encoding="utf-8"))
    card = Card(age="adult", build="average", skin="light", hair="short", hair_colour="#222222",
                top="raincoat", top_colour="#2E4A70", bottom="trousers",
                bottom_colour="#1C2230", shoes_colour="#101014")  # fmt: skip
    ep = ep.model_copy(
        update={"characters": [c.model_copy(update={"card": card}) for c in ep.characters]}
    )
    beat = ep.beats[0]
    words = [Word(w, 0.2 + i * 0.4, 0.5 + i * 0.4) for i, w in enumerate(beat.text.split())]
    style = Styles(settings.styles).get(settings.style)
    out = settings.jobs / "smoke" / "beat01"
    data = scene_input(
        ep, 0, code=fallback(beat, ep.place(beat.place).kind, {}), words=words,
        seconds=words[-1].end + 0.35, style=style, settings=settings, keys=[1.0], out=out,
    )  # fmt: skip
    return await keys(settings, data)


@app.command(name="styles")
def list_styles() -> None:
    """The styles in REELSMITH_STYLES."""
    for name in Styles(_settings().styles).names():
        typer.echo(name)


def _slug(text: str) -> str:
    return re.sub(r"[^\w]+", "-", text.lower()).strip("-")[:40] or "video"
