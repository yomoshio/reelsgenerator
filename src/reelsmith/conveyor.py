"""Drives a batch through the stages one stage at a time, and keeps one model family on
the card at a time."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

import structlog

from reelsmith.models import Job, Rewind, StageError
from reelsmith.pipeline import Services, Stage
from reelsmith.store import Store

log = structlog.get_logger()


class GpuTenant(Protocol):
    """A service that keeps weights on the GPU and can be asked to drop them."""

    async def release(self) -> None: ...


class Gpu:
    """Ollama, ComfyUI and the TTS server each grab VRAM on first use and hold it. On a 32 GB
    card any two of them together run out of memory, so before a stage starts whoever held
    the card last is asked to unload."""

    def __init__(self, tenants: Mapping[str, GpuTenant]) -> None:
        self._tenants = dict(tenants)
        self._holder: str | None = None

    @property
    def holder(self) -> str | None:
        return self._holder

    async def use(self, name: str | None) -> None:
        if name is None or name == self._holder:
            return
        previous = self._tenants.get(self._holder or "")
        if previous is not None:
            log.info("gpu.handover", released=self._holder, acquired=name)
            await previous.release()
        self._holder = name

    async def release_all(self) -> None:
        for tenant in self._tenants.values():
            await tenant.release()
        self._holder = None


class Conveyor:
    """Loading Wan 2.2 takes longer than animating a single shot, so every model is loaded
    once per batch: all claimed jobs get scripts, then all get voices, and so on.

    Only StageError and Rewind are job-level outcomes. Anything else is a bug or a dead
    dependency: the process exits, docker restarts it, and the lease on the claimed jobs
    expires so another turn picks them up."""

    def __init__(
        self,
        stages: Sequence[Stage],
        store: Store,
        services: Services,
        gpu: Gpu,
        *,
        batch_size: int,
        max_attempts: int,
    ) -> None:
        self._stages = stages
        self._store = store
        self._services = services
        self._gpu = gpu
        self._batch_size = batch_size
        self._max_attempts = max_attempts

    async def turn(self) -> int:
        """Returns how many jobs were worked on; zero means the queue is idle."""
        worked = 0
        for stage in self._stages:
            jobs = await self._store.claim(stage.takes, self._batch_size, settled=stage.settled)
            if jobs:
                await self._gpu.use(stage.gpu)
            for job in jobs:
                await self._push(stage, job)
                worked += 1
        return worked

    async def run_forever(
        self, idle_seconds: float, before_turn: Callable[[], Awaitable[bool]] | None = None
    ) -> None:
        """`before_turn` runs ahead of every turn; when it returns False the turn is skipped
        and the card is released, which is how a pause from the ComfyUI blocks works."""
        while True:
            if before_turn is not None and not await before_turn():
                await self._gpu.release_all()
                await asyncio.sleep(idle_seconds)
                continue
            if await self.turn() == 0:
                await self._gpu.release_all()
                await asyncio.sleep(idle_seconds)

    async def _push(self, stage: Stage, job: Job) -> None:
        bound = log.bind(job=str(job.id), stage=stage.name)
        try:
            await stage.run(job, self._services)
        except Rewind as back:
            job.rewind(back.to, back.reason, self._max_attempts)
            bound.warning("stage.rewound", reason=back.reason, status=job.status.value)
        except StageError as exc:
            job.fail(str(exc), self._max_attempts)
            bound.warning("stage.failed", error=str(exc), attempt=job.attempts)
        else:
            job.status = job.status.next()
            bound.info("stage.done", status=job.status.value)
        await self._store.save(job)
