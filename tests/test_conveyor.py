from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest

from reelsmith.conveyor import Conveyor, Gpu, lanes
from reelsmith.models import Job, Rewind, StageError, Status
from reelsmith.pipeline import Services, Stage
from reelsmith.store import MemoryJobs
from tests.fakes import job, services


@dataclass
class Tenant:
    released: int = 0

    async def release(self) -> None:
        self.released += 1


@dataclass
class Recorder:
    log: list[tuple[str, str]] = field(default_factory=list)
    broken: set[str] = field(default_factory=set)
    rewind: set[str] = field(default_factory=set)

    def write(self) -> Stage:
        async def run(job: Job, s: Services) -> None:
            self.log.append(("write", job.idea))

        return Stage("write", Status.NEW, "llm", run)

    def speak(self) -> Stage:
        async def run(job: Job, s: Services) -> None:
            if job.idea in self.broken:
                raise StageError("voice server said no")
            if job.idea in self.rewind:
                raise Rewind(Status.NEW, "script unreadable")
            self.log.append(("speak", job.idea))

        return Stage("voice", Status.SCRIPTED, "tts", run)


async def _nothing(job: Job, s: Services) -> None:
    pass


class SpyStore(MemoryJobs):
    def __init__(self) -> None:
        super().__init__()
        self.settled_seen: list[timedelta] = []

    async def claim(
        self, status: Status, limit: int, settled: timedelta = timedelta(0)
    ) -> list[Job]:
        self.settled_seen.append(settled)
        return await super().claim(status, limit, settled)


def _conveyor(
    store: MemoryJobs, *stages: Stage, max_attempts: int = 3
) -> tuple[Conveyor, dict[str, Tenant]]:
    tenants = {"llm": Tenant(), "tts": Tenant()}
    conveyor = Conveyor(
        stages,
        store,
        services(Path("/nowhere")),
        Gpu(tenants),
        batch_size=10,
        max_attempts=max_attempts,
    )
    return conveyor, tenants


async def _queued(store: MemoryJobs, *ideas: str) -> list[Job]:
    jobs = [job(idea) for idea in ideas]
    for j in jobs:
        await store.add(j)
    return jobs


async def test_a_batch_finishes_one_stage_before_the_next_starts() -> None:
    store, seen = MemoryJobs(), Recorder()
    await _queued(store, "zombies", "asylum", "lighthouse")
    conveyor, tenants = _conveyor(store, seen.write(), seen.speak())

    worked = await conveyor.turn()

    assert worked == 6
    assert [step for step, _ in seen.log] == ["write"] * 3 + ["speak"] * 3
    assert tenants["llm"].released == 1
    assert tenants["tts"].released == 0
    assert {j.status for j in await store.find()} == {Status.VOICED}


async def test_a_failing_job_stays_put_and_does_not_stop_the_batch() -> None:
    store, seen = MemoryJobs(), Recorder(broken={"asylum"})
    bad, _ = await _queued(store, "asylum", "zombies")
    conveyor, _ = _conveyor(store, seen.write(), seen.speak())

    await conveyor.turn()

    parked = await store.get(bad.id)
    assert (parked.status, parked.attempts, parked.last_error) == (
        Status.SCRIPTED,
        1,
        "voice server said no",
    )
    assert ("speak", "zombies") in seen.log


async def test_an_empty_queue_moves_nothing_and_touches_no_gpu() -> None:
    conveyor, tenants = _conveyor(MemoryJobs(), Recorder().write())

    assert await conveyor.turn() == 0
    assert all(t.released == 0 for t in tenants.values())


async def test_rewind_sends_the_job_back_and_counts_an_attempt() -> None:
    store, seen = MemoryJobs(), Recorder(rewind={"asylum"})
    (one,) = await _queued(store, "asylum")
    conveyor, _ = _conveyor(store, seen.write(), seen.speak())

    worked = await conveyor.turn()

    back = await store.get(one.id)
    assert worked == 2
    assert (back.status, back.attempts, back.last_error) == (Status.NEW, 1, "script unreadable")


async def test_a_job_fails_for_good_after_max_attempts() -> None:
    store, seen = MemoryJobs(), Recorder(broken={"asylum"})
    (one,) = await _queued(store, "asylum")
    conveyor, _ = _conveyor(store, seen.write(), seen.speak(), max_attempts=2)

    await conveyor.turn()
    assert (await store.get(one.id)).status is Status.SCRIPTED
    await conveyor.turn()

    assert (await store.get(one.id)).status is Status.FAILED


async def test_settled_is_passed_to_claim() -> None:
    store = SpyStore()
    settle = Stage("measure", Status.PUBLISHED, None, _nothing, settled=timedelta(hours=1))
    conveyor, _ = _conveyor(store, settle)

    await conveyor.turn()

    assert store.settled_seen == [timedelta(hours=1)]


async def test_gpu_hands_over_only_between_different_tenants() -> None:
    tenants = {"llm": Tenant(), "comfy": Tenant()}
    gpu = Gpu(tenants)

    await gpu.use("llm")
    await gpu.use("llm")
    await gpu.use(None)
    assert (gpu.holder, tenants["llm"].released) == ("llm", 0)

    await gpu.use("comfy")
    assert (gpu.holder, tenants["llm"].released) == ("comfy", 1)

    await gpu.use("unknown")
    assert (gpu.holder, tenants["comfy"].released) == ("unknown", 1)

    await gpu.release_all()
    assert gpu.holder is None
    assert (tenants["llm"].released, tenants["comfy"].released) == (2, 2)


async def test_a_shared_card_unloads_nothing_until_the_conveyor_pauses() -> None:
    tenants = {"llm": Tenant(), "comfy": Tenant()}
    gpu = Gpu(tenants, shared=True)

    await gpu.use("llm")
    await gpu.use("comfy")
    await gpu.use("llm")
    assert [t.released for t in tenants.values()] == [0, 0]

    await gpu.release_all()
    assert [t.released for t in tenants.values()] == [1, 1]


class Stop(Exception):
    pass


@pytest.mark.parametrize(("shared", "released"), [(False, 1), (True, 0)])
async def test_an_idle_conveyor_frees_the_card_unless_it_is_shared(
    shared: bool, released: int
) -> None:
    tenant = Tenant()
    conveyor = Conveyor(
        [Recorder().write()],
        MemoryJobs(),
        services(Path("/nowhere")),
        Gpu({"llm": tenant}, shared=shared),
        batch_size=1,
        max_attempts=1,
    )
    turns = 0

    async def before() -> bool:
        nonlocal turns
        turns += 1
        if turns > 1:
            raise Stop
        return True

    with pytest.raises(Stop):
        await conveyor.run_forever(0, before_turn=before)

    assert tenant.released == released


async def test_each_lane_on_a_shared_card_unloads_only_its_own_models() -> None:
    stages = [
        Stage("write", Status.NEW, "llm", _nothing),
        Stage("voice", Status.SCRIPTED, "tts", _nothing),
        Stage("paint", Status.VOICED, "comfy", _nothing),
        Stage("publish", Status.APPROVED, None, _nothing),
    ]
    tenants = {"llm": Tenant(), "tts": Tenant(), "comfy": Tenant()}

    (rest, rest_gpu), (drawn, drawn_gpu) = lanes(stages, tenants)
    await drawn_gpu.release_all()

    assert [s.name for s in rest] == ["write", "voice", "publish"]
    assert [s.name for s in drawn] == ["paint"]
    assert rest_gpu.shared
    assert drawn_gpu.shared
    assert {name: t.released for name, t in tenants.items()} == {"llm": 0, "tts": 0, "comfy": 1}
