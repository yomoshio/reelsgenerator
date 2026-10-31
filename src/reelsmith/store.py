"""The queue. Postgres in production, memory for tests and the demo.

A claim takes a lease instead of a lock held for hours of rendering: if the worker dies,
the lease runs out and the next turn picks the jobs up again."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from reelsmith.models import Assets, Call, Job, Metrics, Recipe, Script, Status, Verdict


class Store(Protocol):
    async def add(self, job: Job) -> None: ...

    async def get(self, job_id: UUID) -> Job: ...

    async def claim(
        self, status: Status, limit: int, settled: timedelta = timedelta(0)
    ) -> list[Job]: ...

    async def save(self, job: Job) -> None: ...

    async def find(
        self, *, experiment: str | None = None, status: Status | None = None
    ) -> list[Job]: ...

    async def summary(self) -> dict[str, int]: ...


_COLUMNS = """id, idea, status, recipe, attempts, last_error, script, critique, qa, assets,
    calls, experiment, arm, parent, rating, metrics"""

_INSERT = f"""
insert into jobs ({_COLUMNS})
values (%(id)s, %(idea)s, %(status)s, %(recipe)s, %(attempts)s, %(last_error)s, %(script)s,
    %(critique)s, %(qa)s, %(assets)s, %(calls)s, %(experiment)s, %(arm)s, %(parent)s,
    %(rating)s, %(metrics)s)
"""

_CLAIM = f"""
update jobs set lease_until = now() + make_interval(mins => %(lease)s)
where id in (
    select id from jobs
    where status = %(status)s
      and (lease_until is null or lease_until < now())
      and updated_at <= now() - %(settled)s
    order by created_at
    limit %(limit)s
    for update skip locked
)
returning {_COLUMNS}
"""

_SAVE = """
update jobs
set status = %(status)s, attempts = %(attempts)s, last_error = %(last_error)s,
    script = %(script)s, critique = %(critique)s, qa = %(qa)s, assets = %(assets)s,
    calls = %(calls)s, experiment = %(experiment)s, arm = %(arm)s, rating = %(rating)s,
    metrics = %(metrics)s, lease_until = null, updated_at = now()
where id = %(id)s
"""

_FIND = f"""
select {_COLUMNS} from jobs
where (%(experiment)s::text is null or experiment = %(experiment)s::text)
  and (%(status)s::text is null or status = %(status)s::text)
order by created_at
"""


class PostgresJobs:
    def __init__(self, pool: AsyncConnectionPool, *, lease_minutes: int) -> None:
        self._pool = pool
        self._lease = lease_minutes

    async def migrate(self, folder: Path) -> None:
        async with self._pool.connection() as conn:
            for script in sorted(folder.glob("*.sql")):  # noqa: ASYNC240 - runs once, at deploy
                await conn.execute(script.read_bytes())

    async def add(self, job: Job) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(_INSERT, _row(job))

    async def get(self, job_id: UUID) -> Job:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(f"select {_COLUMNS} from jobs where id = %s", (job_id,))
            row = await cur.fetchone()
        if row is None:
            raise LookupError(f"no job {job_id}")
        return _job(row)

    async def claim(
        self, status: Status, limit: int, settled: timedelta = timedelta(0)
    ) -> list[Job]:
        params = {"lease": self._lease, "status": status.value, "limit": limit, "settled": settled}
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_CLAIM, params)
            return [_job(row) for row in await cur.fetchall()]

    async def save(self, job: Job) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(_SAVE, _row(job))

    async def find(
        self, *, experiment: str | None = None, status: Status | None = None
    ) -> list[Job]:
        params = {"experiment": experiment, "status": status.value if status else None}
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_FIND, params)
            return [_job(row) for row in await cur.fetchall()]

    async def summary(self) -> dict[str, int]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("select status, count(*) from jobs group by status")
            return {status: count for status, count in await cur.fetchall()}


def _row(job: Job) -> dict[str, Any]:
    def json(model: Any) -> Jsonb | None:
        return Jsonb(model.model_dump(mode="json")) if model is not None else None

    return {
        "id": job.id,
        "idea": job.idea,
        "status": job.status.value,
        "recipe": json(job.recipe),
        "attempts": job.attempts,
        "last_error": job.last_error,
        "script": json(job.script),
        "critique": json(job.critique),
        "qa": json(job.qa),
        "assets": json(job.assets),
        "calls": Jsonb([c.model_dump(mode="json") for c in job.calls]),
        "experiment": job.experiment,
        "arm": job.arm,
        "parent": job.parent,
        "rating": job.rating,
        "metrics": json(job.metrics),
    }


def _job(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"],
        idea=row["idea"],
        status=Status(row["status"]),
        recipe=Recipe.model_validate(row["recipe"]),
        attempts=row["attempts"],
        last_error=row["last_error"],
        script=Script.model_validate(row["script"]) if row["script"] else None,
        critique=Verdict.model_validate(row["critique"]) if row["critique"] else None,
        qa=Verdict.model_validate(row["qa"]) if row["qa"] else None,
        assets=Assets.model_validate(row["assets"]),
        calls=[Call.model_validate(c) for c in row["calls"]],
        experiment=row["experiment"],
        arm=row["arm"],
        parent=row["parent"],
        rating=row["rating"],
        metrics=Metrics.model_validate(row["metrics"]) if row["metrics"] else None,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Row:
    job: Job
    created: datetime
    saved: datetime
    leased_until: datetime | None = None


@dataclass
class MemoryJobs:
    lease: timedelta = timedelta(minutes=45)
    clock: Callable[[], datetime] = _utcnow
    _rows: dict[UUID, _Row] = field(default_factory=dict, init=False)

    async def add(self, job: Job) -> None:
        now = self.clock()
        self._rows[job.id] = _Row(job, now, now)

    async def get(self, job_id: UUID) -> Job:
        try:
            return self._rows[job_id].job
        except KeyError:
            raise LookupError(f"no job {job_id}") from None

    async def claim(
        self, status: Status, limit: int, settled: timedelta = timedelta(0)
    ) -> list[Job]:
        now = self.clock()
        free = [
            row
            for row in sorted(self._rows.values(), key=lambda r: r.created)
            if row.job.status is status
            and (row.leased_until is None or row.leased_until < now)
            and row.saved <= now - settled
        ]
        for row in free[:limit]:
            row.leased_until = now + self.lease
        return [row.job for row in free[:limit]]

    async def save(self, job: Job) -> None:
        row = self._rows[job.id]
        row.job = job
        row.saved = self.clock()
        row.leased_until = None

    async def find(
        self, *, experiment: str | None = None, status: Status | None = None
    ) -> list[Job]:
        return [
            row.job
            for row in sorted(self._rows.values(), key=lambda r: r.created)
            if (experiment is None or row.job.experiment == experiment)
            and (status is None or row.job.status is status)
        ]

    async def summary(self) -> dict[str, int]:
        return dict(Counter(row.job.status.value for row in self._rows.values()))
