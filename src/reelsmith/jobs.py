"""A job is a folder in `jobs/`: `job.json` with its status and log, and every file the
stages make, each stage reading what the one before wrote. Stages run one at a time over
every job waiting for them, so a model stays loaded while it has work."""

import secrets
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from reelsmith.catalog import Catalog
from reelsmith.llm import Llm
from reelsmith.settings import Settings
from reelsmith.styles import Styles

log = structlog.get_logger()


class JobError(Exception):
    pass


class Status(StrEnum):
    NEW = "new"
    WRITTEN = "written"
    VOICED = "voiced"
    STAGED = "staged"
    RENDERED = "rendered"
    ASSEMBLED = "assembled"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class Source(BaseModel):
    kind: Literal["idea", "story", "book"]
    text: str
    title: str = ""


class Entry(BaseModel):
    at: datetime
    step: str
    model: str = ""
    seconds: float = 0.0
    note: str = ""


class Job(BaseModel):
    id: str
    created: datetime
    style: str
    source: Source
    status: Status = Status.NEW
    failed_at: Status | None = Field(default=None, description="Where a failed job stopped.")
    error: str | None = None
    tries: int = 0
    log: list[Entry] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    notes: str = ""

    def note(self, step: str, *, model: str = "", seconds: float = 0.0, note: str = "") -> None:
        self.log.append(
            Entry(at=datetime.now(UTC), step=step, model=model, seconds=seconds, note=note)
        )


class Jobs:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, source: Source, style: str) -> Job:
        now = datetime.now(UTC)
        job = Job(id=f"{now:%m%d}-{secrets.token_hex(3)}", created=now, style=style, source=source)
        self.folder(job).mkdir(parents=True)
        (self.folder(job) / "source.txt").write_text(source.text, encoding="utf-8")
        self.save(job)
        return job

    def folder(self, job: Job) -> Path:
        return self.root / job.id

    def save(self, job: Job) -> None:
        path = self.folder(job) / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(job.model_dump_json(indent=1), encoding="utf-8")
        temporary.replace(path)

    def all(self) -> list[Job]:
        found = [
            Job.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self.root.glob("*/job.json")
        ]
        return sorted(found, key=lambda j: j.created)

    def get(self, prefix: str) -> Job:
        found = [j for j in self.all() if j.id.startswith(prefix) or j.id.endswith(prefix)]
        if len(found) != 1:
            what = "no job" if not found else f"{len(found)} jobs"
            raise JobError(f"{what} match {prefix!r}")
        return found[0]


@dataclass
class Context:
    settings: Settings
    llm: Llm
    styles: Styles
    speech: Any = None
    catalog: Callable[[str], Catalog] | None = None


Step = Callable[[Job, Path, Context], Awaitable[None]]


@dataclass(frozen=True)
class Stage:
    name: str
    takes: Status
    gives: Status
    run: Step


async def run_once(jobs: Jobs, ctx: Context, stages: Sequence[Stage]) -> int:
    """Each stage in turn over every job waiting for it. A failed step leaves the job where it
    was with the error recorded, and the next job goes on; after `tries` failures the job is
    failed. Gives how many steps succeeded."""
    done = 0
    for stage in stages:
        for job in [j for j in jobs.all() if j.status == stage.takes]:
            started = time.monotonic()
            try:
                await stage.run(job, jobs.folder(job), ctx)
            except Exception as exc:
                job.tries += 1
                job.error = f"{stage.name}: {exc}"
                if job.tries >= ctx.settings.tries:
                    job.status, job.failed_at = Status.FAILED, job.status
                job.note(stage.name, seconds=time.monotonic() - started, note=f"failed: {exc}")
                log.warning("step failed", job=job.id, stage=stage.name, error=str(exc))
            else:
                job.status, job.error, job.tries = stage.gives, None, 0
                job.note(stage.name, seconds=time.monotonic() - started)
                done += 1
            jobs.save(job)
    return done


# What each step leaves in the job's folder. A job sent back loses the work of the later
# steps: left in place, a scene of the old story would be taken for one of the new.
_MADE = {
    Status.NEW: ["plan.json", "script.md", "episode.json"],
    Status.WRITTEN: ["voice"],
    Status.VOICED: ["scenes", "keys"],
    Status.STAGED: ["clips"],
    Status.RENDERED: ["final.mp4", "check.json", "post.txt", "storyboard.jpg"],
}


def forget(folder: Path, status: Status) -> None:
    """Removes what the step that starts at `status` and every later step made."""
    steps = list(_MADE)
    if status not in steps:
        return
    for step in steps[steps.index(status) :]:
        for name in _MADE[step]:
            made = folder / name
            if made.is_dir():
                shutil.rmtree(made)
            else:
                made.unlink(missing_ok=True)
