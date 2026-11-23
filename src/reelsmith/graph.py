"""The pipeline as steps a graph editor can run one at a time: a job made from an idea, and
each stage moved on by itself. A step that already ran with the same settings is skipped,
and one whose settings changed is run again together with everything after it, so changing
the voice redoes the voice and the picture's timing but not the story.

The ComfyUI nodes in comfyui/ are thin wrappers over this module; nothing here knows of
ComfyUI."""

import hashlib
import json
from pathlib import Path
from typing import Any

from reelsmith.jobs import Context, Job, JobError, Jobs, Source, Stage, Status, forget
from reelsmith.llm import Llm
from reelsmith.runtime import catalog
from reelsmith.settings import Settings
from reelsmith.stages import stages
from reelsmith.styles import Styles
from reelsmith.voice import Speech

ORDER = ["write", "voice", "stage", "render", "assemble"]
# The settings each step reads. A change in one of them is a reason to run that step again.
READS: dict[str, list[str]] = {
    "write": ["planner", "editor", "director", "language", "temperature", "reasoning"],
    "voice": ["tts", "voice_url", "speech_url", "retakes"],
    "stage": ["staging", "planner", "coder", "vision", "rounds", "variants"],
    "render": [],
    "assemble": [],
}
_PATHS = ["jobs", "styles", "runtime", "library", "outbox"]


def settings(root: str | Path, **overrides: Any) -> Settings:
    """The settings of the reelsmith folder at `root`, read from its .env, with the given
    values on top. Its folders are made absolute: a graph editor runs from a folder of its
    own."""
    base = Path(root).expanduser().resolve()
    given = {k: v for k, v in overrides.items() if v not in ("", None)}
    made = Settings(_env_file=base / ".env", **given)
    moved = {
        name: base / getattr(made, name)
        for name in _PATHS
        if hasattr(made, name) and not Path(getattr(made, name)).is_absolute()
    }
    return made.model_copy(update=moved)


def job_for(made: Settings, text: str, style: str = "") -> Job:
    """The job of this idea in this style: the one already in the queue, or a new one. Run
    twice, a graph does not fill the queue with copies."""
    text = text.strip()
    if not text:
        raise JobError("the idea is empty")
    chosen = style or made.style
    Styles(made.styles).get(chosen)
    jobs = Jobs(made.jobs)
    for job in reversed(jobs.all() if made.jobs.is_dir() else []):
        if job.source.text == text and job.style == chosen and job.status != Status.REJECTED:
            return job
    return jobs.create(Source(kind="idea", text=text), chosen)


def _print(made: Settings, step: str) -> str:
    read = {name: str(getattr(made, name, "")) for name in READS[step]}
    return hashlib.sha256(json.dumps(read, sort_keys=True).encode()).hexdigest()[:16]


def _ran(folder: Path) -> dict[str, str]:
    path = folder / "graph.json"
    return dict(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}


async def advance(made: Settings, job_id: str, step: str, steps: list[Stage] | None = None) -> Job:
    """Runs one step of a job and gives the job as it then stands. A step done before with
    the same settings is left alone; done with other settings, it and the later steps are
    forgotten and it runs again. A step whose turn has not come says which one comes first."""
    order = {s.name: s for s in (steps or stages())}
    stage = order[step]
    jobs = Jobs(made.jobs)
    job = jobs.get(job_id)
    folder = jobs.folder(job)
    ran = _ran(folder)
    states = [s.takes for s in order.values()] + [list(order.values())[-1].gives]
    if job.status == Status.FAILED and job.failed_at is not None:
        job.status, job.error, job.tries = job.failed_at, None, 0
    if job.status not in states:
        raise JobError(f"job {job.id} is {job.status}: it is out of the queue")
    here, wanted = states.index(job.status), states.index(stage.takes)
    if here < wanted:
        first = list(order.values())[here].name
        raise JobError(f"job {job.id} is {job.status}: connect and run the {first} step first")
    if here > wanted:
        if ran.get(step) == _print(made, step):
            return job
        forget(folder, stage.takes)
        job.status = stage.takes
        ran = {name: mark for name, mark in ran.items() if ORDER.index(name) < ORDER.index(step)}
    llm = Llm(made.llm_url, temperature=made.temperature, reasoning=made.reasoning)
    speech = Speech(made.speech_url, reader=made.reader())
    ctx = Context(made, llm, Styles(made.styles), speech)
    ctx.catalog = lambda text: catalog(made, text)
    try:
        await stage.run(job, folder, ctx)
    except Exception as exc:
        job.error = f"{step}: {exc}"
        jobs.save(job)
        raise JobError(f"{step} failed for job {job.id}: {exc}") from exc
    finally:
        await llm.close()
        await speech.close()
    job.status, job.error, job.tries = stage.gives, None, 0
    jobs.save(job)
    ran[step] = _print(made, step)
    (folder / "graph.json").write_text(json.dumps(ran, indent=1), encoding="utf-8")
    return job


def seen(made: Settings, job_id: str) -> dict[str, Any]:
    """What there is to look at in a job: the film, the storyboard and the middle keyframe
    of every beat with its lines."""
    jobs = Jobs(made.jobs)
    job = jobs.get(job_id)
    folder = jobs.folder(job)
    film = folder / "final.mp4"
    episode = folder / "episode.json"
    lines: list[str] = []
    if episode.is_file():
        beats = json.loads(episode.read_text(encoding="utf-8")).get("beats", [])
        lines = [" ".join(b.get("lines", [])) for b in beats]
    return {
        "job": job.id,
        "status": str(job.status),
        "error": job.error or "",
        "film": film if film.is_file() else None,
        "keys": sorted((folder / "keys").glob("beat*-1.png")),
        "lines": lines,
    }
