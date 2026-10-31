"""Builds the services from settings and wires the conveyor. The demo lives here too."""

from collections.abc import AsyncIterator, Collection
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import httpx
from psycopg_pool import AsyncConnectionPool

from reelsmith.conveyor import Conveyor, Gpu, GpuTenant
from reelsmith.models import Job, Recipe, Status
from reelsmith.pipeline import STAGES, Animator, Painter, Services, Stage
from reelsmith.pricing import DEFAULT, Tariff
from reelsmith.report import Arm, Report, compare, report
from reelsmith.services import synthetic
from reelsmith.services.comfy import (
    ComfyAnimator,
    ComfyClient,
    ComfyComposer,
    ComfyPainter,
    Workflow,
)
from reelsmith.services.ffmpeg import FfmpegMontage
from reelsmith.services.ollama import OllamaLlm
from reelsmith.services.outbox import OutboxPublisher
from reelsmith.services.voxcpm import VoxNarrator
from reelsmith.services.whisper import WhisperTranscriber
from reelsmith.settings import Settings
from reelsmith.store import MemoryJobs, PostgresJobs, Store

WAN_GRAPHS = {"wan-2.2": ("animate.json", 16), "wan-5b": ("animate-draft.json", 24)}
DEMO_IDEAS = (
    "зомби в ночном метро",
    "пациент, который не спит",
    "маяк, который зажигается сам",
    "лифт без кнопки первого этажа",
    "ночная смена в архиве",
)
DEMO_FLAG, DEMO_REJECT = 0.2, 0.15


@dataclass(frozen=True)
class App:
    jobs: Store
    conveyor: Conveyor


@asynccontextmanager
async def database(settings: Settings) -> AsyncIterator[PostgresJobs]:
    async with AsyncConnectionPool(
        settings.database_url, min_size=1, max_size=4, open=False
    ) as pool:
        yield PostgresJobs(pool, lease_minutes=settings.lease_minutes)


def local_services(
    settings: Settings,
    *,
    ollama: httpx.AsyncClient,
    comfy: httpx.AsyncClient,
    tts: httpx.AsyncClient,
) -> tuple[Services, dict[str, GpuTenant]]:
    """The three graphs every run needs must be exported; the 5B draft graph is optional
    and only adds the `wan-5b` model when present."""
    llm = OllamaLlm(
        ollama,
        writer_model=settings.writer_model,
        judge_model=settings.judge_model,
        language=settings.language,
    )
    client = ComfyClient(comfy)
    narrator = VoxNarrator(tts, settings.voice)

    def graph(file: str) -> Workflow:
        path = settings.workflows / file
        if not path.exists():
            raise FileNotFoundError(
                f"export {file} into {settings.workflows}; see workflows/README.md"
            )
        return Workflow.load(path)

    painters: dict[str, Painter] = {"z-image": ComfyPainter(client, graph("keyframe.json"))}
    animators: dict[str, Animator] = {}
    for name, (file, fps) in WAN_GRAPHS.items():
        if name == "wan-2.2" or (settings.workflows / file).exists():
            animators[name] = ComfyAnimator(client, graph(file), name=name, fps=fps)

    services = Services(
        llm=llm,
        painters=painters,
        animators=animators,
        narrator=narrator,
        composer=ComfyComposer(client, graph("score.json")),
        transcriber=WhisperTranscriber(settings.whisper_model, settings.language),
        montage=FfmpegMontage(),
        publisher=OutboxPublisher(settings.outbox),
        tariff=settings.tariff(),
        media=settings.media_root,
    )
    return services, {"llm": llm, "comfy": client, "tts": narrator}


def synthetic_services(
    *,
    media: Path,
    outbox: Path,
    tariff: Tariff,
    flag: float = 0.0,
    reject: float = 0.0,
    analytics: bool = False,
) -> Services:
    """The same model names as the local set, so a synthetic run prices like a real one."""
    montage = FfmpegMontage()
    return Services(
        llm=synthetic.SyntheticLlm(flag=flag, reject=reject),
        painters={"z-image": synthetic.SyntheticPainter("z-image")},
        animators={
            "wan-2.2": synthetic.SyntheticAnimator("wan-2.2"),
            "wan-5b": synthetic.SyntheticAnimator("wan-5b"),
        },
        narrator=synthetic.SyntheticNarrator(),
        composer=synthetic.SyntheticComposer(),
        transcriber=synthetic.SyntheticTranscriber(montage),
        montage=montage,
        publisher=OutboxPublisher(outbox),
        tariff=tariff,
        media=media,
        analytics=synthetic.SyntheticAnalytics() if analytics else None,
    )


def stages_for(services: Services, names: Collection[str] | None = None) -> list[Stage]:
    """The conveyor in order; `measure` only where analytics can be read by code."""
    chosen = [s for s in STAGES if s.name != "measure" or services.analytics is not None]
    if names is None:
        return chosen
    wanted = {n.lower() for n in names}
    unknown = wanted - {s.name for s in STAGES}
    if unknown:
        raise ValueError(f"no stages named {sorted(unknown)}")
    return [s for s in chosen if s.name in wanted]


@asynccontextmanager
async def application(
    settings: Settings, *, stage_names: Collection[str] | None = None
) -> AsyncIterator[App]:
    async with AsyncExitStack() as stack:
        jobs = await stack.enter_async_context(database(settings))
        tenants: dict[str, GpuTenant] = {}
        if settings.services == "synthetic":
            services = synthetic_services(
                media=settings.media_root, outbox=settings.outbox, tariff=settings.tariff()
            )
        else:
            http = [
                await stack.enter_async_context(httpx.AsyncClient(base_url=url))
                for url in (settings.ollama_url, settings.comfy_url, settings.tts_url)
            ]
            services, tenants = local_services(settings, ollama=http[0], comfy=http[1], tts=http[2])
        if stage_names is None:
            services.check(settings.recipe())
        conveyor = Conveyor(
            stages_for(services, stage_names),
            jobs,
            services,
            Gpu(tenants),
            batch_size=settings.batch_size,
            max_attempts=settings.max_attempts,
        )
        yield App(jobs, conveyor)


@dataclass(frozen=True)
class DemoResult:
    jobs: list[Job]
    arms: list[Arm]
    report: Report


async def demo(
    ideas: list[str], *, arm_a: Recipe, arm_b: Recipe, out: Path, tariff: Tariff = DEFAULT
) -> DemoResult:
    """The whole conveyor in memory on synthetic models, with arm B forked on the same frames.

    Nothing here reaches a model or a database; ffmpeg does the only real work. The point is
    to watch the gates, the rewinds, the cost ledger and the comparison behave end to end."""
    services = synthetic_services(
        media=out / "media",
        outbox=out / "outbox",
        tariff=tariff,
        flag=DEMO_FLAG,
        reject=DEMO_REJECT,
        analytics=True,
    )
    stages = [replace(s, settled=timedelta(0)) for s in stages_for(services)]
    store = MemoryJobs()
    parents = [Job.new(idea, arm_a) for idea in ideas]
    for job in parents:
        await store.add(job)

    def conveyor(chosen: list[Stage]) -> Conveyor:
        return Conveyor(chosen, store, services, Gpu({}), batch_size=2 * len(ideas), max_attempts=5)

    await _drain(conveyor([s for s in stages if s.takes.before(Status.FRAMED)]))
    for job in parents:
        child = job.fork(arm_b, "B")
        await store.save(job)
        await store.add(child)

    everything = conveyor(stages)
    await _drain(everything)
    for job in await store.find(status=Status.ASSEMBLED):
        job.status = Status.APPROVED
        job.rating = synthetic.rng("rating", job.id).randint(5, 10)
        await store.save(job)
    await _drain(everything)

    jobs = await store.find()
    return DemoResult(jobs, compare(jobs), report(jobs, tariff))


async def _drain(conveyor: Conveyor) -> None:
    while await conveyor.turn():
        pass
