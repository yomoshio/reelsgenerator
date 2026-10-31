import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from reelsmith.models import Call, Metrics, Outcome, Status, Verdict
from reelsmith.store import MemoryJobs, _job, _row
from tests.fakes import job, script


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def test_claim_returns_oldest_first_and_leases() -> None:
    store = MemoryJobs()
    first, second, other = job("a"), job("b"), job("c", Status.SCRIPTED)
    for j in (first, second, other):
        await store.add(j)

    claimed = await store.claim(Status.NEW, limit=1)
    assert [j.id for j in claimed] == [first.id]

    assert [j.id for j in await store.claim(Status.NEW, limit=5)] == [second.id]
    assert await store.claim(Status.NEW, limit=5) == []


async def test_save_releases_the_lease() -> None:
    store = MemoryJobs()
    one = job("a")
    await store.add(one)
    (claimed,) = await store.claim(Status.NEW, limit=1)

    await store.save(claimed)

    assert [j.id for j in await store.claim(Status.NEW, limit=1)] == [one.id]


async def test_lease_expires() -> None:
    clock = Clock()
    store = MemoryJobs(lease=timedelta(minutes=45), clock=clock)
    await store.add(job("a"))
    await store.claim(Status.NEW, limit=1)

    clock.now += timedelta(minutes=46)

    assert len(await store.claim(Status.NEW, limit=1)) == 1


async def test_settled_hides_recently_saved_jobs() -> None:
    clock = Clock()
    store = MemoryJobs(clock=clock)
    one = job("a", Status.PUBLISHED)
    await store.add(one)
    await store.save(one)

    assert await store.claim(Status.PUBLISHED, 5, settled=timedelta(hours=24)) == []
    clock.now += timedelta(hours=25)
    assert len(await store.claim(Status.PUBLISHED, 5, settled=timedelta(hours=24))) == 1


async def test_find_filters_by_experiment_and_status() -> None:
    store = MemoryJobs()
    a, b, c = job("a", Status.FRAMED), job("b", Status.FRAMED), job("c")
    a.experiment = b.experiment = "x"
    for j in (a, b, c):
        await store.add(j)

    assert {j.id for j in await store.find(experiment="x")} == {a.id, b.id}
    assert {j.id for j in await store.find(status=Status.NEW)} == {c.id}
    assert {j.id for j in await store.find(experiment="x", status=Status.NEW)} == set()
    assert len(await store.find()) == 3


async def test_get_raises_lookup_error() -> None:
    with pytest.raises(LookupError):
        await MemoryJobs().get(uuid4())


async def test_summary_counts_statuses() -> None:
    store = MemoryJobs()
    for j in (job("a"), job("b"), job("c", Status.FAILED)):
        await store.add(j)

    assert await store.summary() == {"new": 2, "failed": 1}


def test_job_round_trips_through_the_postgres_row() -> None:
    original = job(status=Status.MEASURED, script=script())
    original.assets.frames = {0: "x/frames/00-1.png"}
    original.assets.candidates = {0: ["x/frames/00-0.png", "x/frames/00-1.png"]}
    original.calls.append(
        Call(stage="animate", provider="wan-2.2", units=5, usd=0.5, outcome=Outcome.FLAGGED, shot=0)
    )
    original.critique = Verdict(score=7.5, notes="ok")
    original.qa = Verdict(score=8.0, bad_shots=[])
    original.metrics = Metrics(views=10, retention_3s=0.5, completion=0.3)
    original.experiment, original.arm, original.rating = "x", "A", 7

    stored = {
        k: json.loads(json.dumps(v.obj)) if isinstance(v, Jsonb) else v
        for k, v in _row(original).items()
    }

    assert _job(stored) == original
