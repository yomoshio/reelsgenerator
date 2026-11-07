"""Builds the services from settings and wires the conveyor. The demo lives here too."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import partial
from pathlib import Path

import httpx
from psycopg_pool import AsyncConnectionPool

from reelsmith.books import Adapter, make_adaptation
from reelsmith.conveyor import Conveyor, Gpu, GpuTenant, lanes
from reelsmith.models import Job, Outline, Recipe, Status
from reelsmith.pipeline import STAGES, Animator, Painter, Services, Stage
from reelsmith.pricing import DEFAULT, Tariff
from reelsmith.report import Arm, Report, compare, report
from reelsmith.series import Serial, make_serial
from reelsmith.services import synthetic
from reelsmith.services.comfy import (
    ComfyAnimator,
    ComfyClient,
    ComfyComposer,
    ComfyPainter,
    Workflow,
)
from reelsmith.services.ffmpeg import FfmpegMontage, StillAnimator
from reelsmith.services.ollama import OllamaLlm
from reelsmith.services.outbox import OutboxPublisher
from reelsmith.services.voxcpm import VoxNarrator
from reelsmith.services.whisper import WhisperTranscriber
from reelsmith.settings import Settings
from reelsmith.store import MemoryJobs, PostgresJobs, Store
from reelsmith.studio import Studio
from reelsmith.styles import Style, Styles

WAN_GRAPHS = {
    "wan-2.2": ("animate.json", 16),
    "wan-2.2-hd": ("animate-hd.json", 16),
    "wan-5b": ("animate-draft.json", 24),
}
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
    """`conveyor` takes the studio's requests; `beside` are lanes that run at the same time
    on a shared card and only check for a pause."""

    jobs: Store
    conveyor: Conveyor
    studio: Studio | None = None
    beside: tuple[Conveyor, ...] = ()

    async def run(self, idle_seconds: float, *, once: bool = False) -> None:
        between = self.studio.sync if self.studio else None
        if not once:
            beside = (lane.run_forever(idle_seconds, self._working) for lane in self.beside)
            await asyncio.gather(
                self.conveyor.run_forever(idle_seconds, before_turn=between), *beside
            )
            return
        if between is None or await between():
            for conveyor in (self.conveyor, *self.beside):
                await conveyor.turn()

    async def _working(self) -> bool:
        return self.studio is None or not self.studio.paused


@asynccontextmanager
async def database(settings: Settings) -> AsyncIterator[PostgresJobs]:
    async with AsyncConnectionPool(
        settings.database_url, min_size=1, max_size=4, open=False
    ) as pool:
        yield PostgresJobs(pool, lease_minutes=settings.lease_minutes)


def ollama_llm(settings: Settings, http: httpx.AsyncClient) -> OllamaLlm:
    return OllamaLlm(
        http,
        writer_model=settings.writer_model,
        judge_model=settings.judge_model,
        language=settings.language,
        writer_temperature=settings.writer_temperature,
        critic_temperature=settings.critic_temperature,
        judge_temperature=settings.judge_temperature,
        context=settings.llm_context,
        keep_alive="24h" if settings.gpu_shared else "15m",
    )


@asynccontextmanager
async def planner(settings: Settings) -> AsyncIterator[Adapter]:
    """The writer model for work outside the conveyor, or its stand-in."""
    if settings.services == "synthetic":
        yield synthetic.SyntheticLlm()
        return
    async with httpx.AsyncClient(base_url=settings.ollama_url) as http:
        yield ollama_llm(settings, http)


async def serial(settings: Settings, synopsis: str, style: Style, episodes: int) -> Serial:
    """A season from a synopsis, on the real writer model or on the stand-in."""
    async with planner(settings) as llm:
        return await make_serial(llm, synopsis, style, episodes)


async def adaptation(
    settings: Settings,
    text: str,
    style: Style,
    most: int,
    progress: Callable[[str], None] = lambda _: None,
) -> Serial:
    """A serial that keeps a finished story's events, at most `most` episodes."""
    async with planner(settings) as llm:
        return await make_adaptation(llm, text, style, most, progress)


async def outlines(settings: Settings, ideas: list[str], style: Style) -> list[Outline]:
    """The writer model's outline for each idea, without rendering anything."""
    async with planner(settings) as llm:
        return [await llm.plan(idea, style) for idea in ideas]


def local_services(
    settings: Settings,
    *,
    ollama: httpx.AsyncClient,
    comfy: httpx.AsyncClient,
    tts: httpx.AsyncClient,
) -> tuple[Services, dict[str, GpuTenant]]:
    """The three graphs in workflows/ are required; `animate-draft.json` is optional and
    adds the `wan-5b` model when present."""
    llm = ollama_llm(settings, ollama)
    client = ComfyClient(comfy)
    narrator = VoxNarrator(tts, settings.voice, cfg=settings.voice_cfg, steps=settings.voice_steps)

    def graph(file: str) -> Workflow:
        path = settings.workflows / file
        if not path.exists():
            raise FileNotFoundError(
                f"export {file} into {settings.workflows}; see docs/workflows.md"
            )
        return Workflow.load(path)

    painter = ComfyPainter(
        client,
        graph("keyframe.json"),
        width=settings.frame_width,
        height=settings.frame_height,
        steps=settings.frame_steps,
    )
    painters: dict[str, Painter] = {"z-image": painter}
    if (settings.workflows / "keyframe-edit.json").exists():
        painters["qwen-edit"] = ComfyPainter(
            client,
            graph("keyframe-edit.json"),
            name="qwen-edit",
            width=settings.frame_width,
            height=settings.frame_height,
            steps=settings.edit_steps,
        )
    animators: dict[str, Animator] = {"still": StillAnimator()}
    for name, (file, fps) in WAN_GRAPHS.items():
        if name == "wan-2.2" or (settings.workflows / file).exists():
            animators[name] = ComfyAnimator(
                client,
                graph(file),
                name=name,
                fps=fps,
                max_seconds=settings.clip_seconds,
                width=settings.clip_width,
                height=settings.clip_height,
                steps=settings.clip_steps,
            )

    services = Services(
        llm=llm,
        painters=painters,
        animators=animators,
        narrator=narrator,
        composer=ComfyComposer(client, graph("score.json"), steps=settings.music_steps),
        transcriber=WhisperTranscriber(settings.whisper_model, settings.language),
        montage=FfmpegMontage(music_level=settings.music_level, still_width=settings.judge_width),
        publisher=OutboxPublisher(settings.outbox),
        tariff=settings.tariff(),
        media=settings.media_root,
        styles=Styles(settings.styles),
        gates=settings.gates(),
        language=settings.language,
        showcase=settings.studio / "output" / "reelsmith" / "videos"
        if settings.studio.is_dir()
        else None,
    )
    return services, {"llm": llm, "comfy": client, "tts": narrator}


def synthetic_services(
    *,
    media: Path,
    outbox: Path,
    styles: Path,
    tariff: Tariff,
    flag: float = 0.0,
    reject: float = 0.0,
    analytics: bool = False,
) -> Services:
    """The same model names as the local set, so a synthetic run prices like a real one."""
    montage = FfmpegMontage()
    return Services(
        llm=synthetic.SyntheticLlm(flag=flag, reject=reject),
        painters={
            "z-image": synthetic.SyntheticPainter("z-image"),
            "qwen-edit": synthetic.SyntheticPainter("qwen-edit"),
        },
        animators={
            "still": StillAnimator(),
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
        styles=Styles(styles),
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
        services, tenants = await services_for(settings, stack)
        if stage_names is None:
            services.check(settings.recipe())
        stages = stages_for(services, stage_names)
        split = lanes(stages, tenants) if settings.gpu_shared else [(stages, Gpu(tenants))]
        main, *beside = [
            Conveyor(
                chosen,
                jobs,
                services,
                gpu,
                batch_size=settings.batch_size,
                max_attempts=settings.max_attempts,
            )
            for chosen, gpu in split
        ]
        studio = studio_for(settings, jobs, services, split[0][1])
        yield App(jobs, main, studio, tuple(beside))


async def services_for(
    settings: Settings, stack: AsyncExitStack
) -> tuple[Services, dict[str, GpuTenant]]:
    """The local services, whose HTTP clients live as long as `stack`, or the stand-ins."""
    if settings.services == "synthetic":
        services = synthetic_services(
            media=settings.media_root,
            outbox=settings.outbox,
            styles=settings.styles,
            tariff=settings.tariff(),
        )
        return services, {}
    http = [
        await stack.enter_async_context(httpx.AsyncClient(base_url=url))
        for url in (settings.ollama_url, settings.comfy_url, settings.tts_url)
    ]
    return local_services(settings, ollama=http[0], comfy=http[1], tts=http[2])


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    seconds: float
    result: str


SMOKE_IDEA = "Утром Артём просыпается, а квартира затоплена"  # noqa: RUF001
SMOKE_LINE = "Артём открывает дверь. Вода уже на лестнице."


async def smoke(settings: Settings, out: Path) -> list[Check]:
    """One call to every model, in the order the conveyor uses them and with the card
    handed over between services the same way, so a fresh machine shows what works. The
    files land in `out`, which must exist."""
    async with AsyncExitStack() as stack:
        services, tenants = await services_for(settings, stack)
        gpu = Gpu(tenants)
        recipe = settings.recipe()
        style = services.styles.get(recipe.style)
        checks: list[Check] = []

        async def step(name: str, tenant: str | None, work: Callable[[], Awaitable[str]]) -> bool:
            await gpu.use(tenant)
            started = time.monotonic()
            try:
                result, ok = await work(), True
            except Exception as exc:  # any failure is a finding on a fresh machine
                result, ok = f"{type(exc).__name__}: {exc}", False
            checks.append(Check(name, ok, time.monotonic() - started, result))
            return ok

        async def plan() -> str:
            outline = await services.llm.plan(SMOKE_IDEA, style)
            return f"{len(outline.beats)} beats, «{outline.title}»"

        voice = out / f"voice{services.narrator.suffix}"
        frame, clip = out / "frame.png", out / "clip.mp4"

        async def speak() -> str:
            await services.narrator.speak(SMOKE_LINE, voice)
            return f"{voice.name}, {await services.montage.seconds(voice):.1f} s"

        async def hear() -> str:
            return " ".join(w.text for w in await services.transcriber.words(voice))

        async def paint() -> str:
            prompt = f"a man in a blue raincoat on a flooded staircase. {style.look.frame}"
            await services.painter(recipe.image).paint(prompt, seed=1, out=frame)
            return frame.name

        async def redraw(model: str) -> str:
            portrait = out / "frame-portrait.png"
            prompt = f"The same person as in the reference image, at a window. {style.look.frame}"
            await services.painter(model).paint(prompt, seed=1, out=portrait, reference=frame)
            return f"{portrait.name} by {model}"

        async def animate() -> str:
            animator = services.animator(recipe.video)
            await animator.animate(frame, "slow push-in", seconds=2.0, seed=1, out=clip)
            return f"{clip.name}, {await services.montage.seconds(clip):.1f} s by {animator.name}"

        async def compose() -> str:
            track = out / f"music{services.composer.suffix}"
            await services.composer.compose("low tense drone", seconds=5.0, seed=1, out=track)
            return f"{track.name}, {await services.montage.seconds(track):.1f} s"

        await step("plan", "llm", plan)
        if await step("voice", "tts", speak):
            await step("subtitles", None, hear)
        if await step("frame", "comfy", paint):
            if model := recipe.cast_image:
                await step("portrait", "comfy", partial(redraw, model))
            await step("clip", "comfy", animate)
        await step("music", "comfy", compose)
        await gpu.release_all()
        return checks


def studio_for(settings: Settings, jobs: Store, services: Services, gpu: Gpu) -> Studio | None:
    """Only where the studio folder is mounted, as it is in compose."""
    if not settings.studio.is_dir():
        return None

    async def series(synopsis: str, style: Style, episodes: int) -> Serial:
        return await serial(settings, synopsis, style, episodes)

    async def book(text: str, style: Style, most: int) -> Serial:
        return await adaptation(settings, text, style, most)

    return Studio(
        settings.studio,
        jobs,
        recipe=settings.recipe(),
        styles=services.styles,
        make_serial=series,
        before_llm=lambda: gpu.use("llm"),
        make_book=book,
    )


@dataclass(frozen=True)
class DemoResult:
    jobs: list[Job]
    arms: list[Arm]
    report: Report


async def demo(
    ideas: list[str],
    *,
    arm_a: Recipe,
    arm_b: Recipe,
    out: Path,
    styles: Path,
    tariff: Tariff = DEFAULT,
) -> DemoResult:
    """The whole conveyor in memory on synthetic models, with arm B forked on the same frames.
    Nothing reaches a model or a database; ffmpeg does the only real work."""
    services = synthetic_services(
        media=out / "media",
        outbox=out / "outbox",
        styles=styles,
        tariff=tariff,
        flag=DEMO_FLAG,
        reject=DEMO_REJECT,
        analytics=True,
    )
    services.check(arm_a)
    services.check(arm_b)
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
