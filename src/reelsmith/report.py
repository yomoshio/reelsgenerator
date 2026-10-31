"""The numbers the research says to decide by. Pure functions over jobs."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import fmean

from reelsmith.models import Call, Job, Outcome, Status
from reelsmith.pipeline import QA_PASS
from reelsmith.pricing import Tariff

_COUNTED = {Outcome.OK, Outcome.FLAGGED}


@dataclass(frozen=True)
class ProviderRow:
    provider: str
    calls: int
    flagged: int
    usd: float
    gpu_hours: float

    @property
    def flag_rate(self) -> float:
        return self.flagged / self.calls if self.calls else 0.0


@dataclass(frozen=True)
class HookRow:
    kind: str
    videos: int
    retention_3s: float
    completion: float


@dataclass(frozen=True)
class Report:
    videos: int
    good: int
    failed: int
    pending: int
    usd: float
    cost_per_good: float | None
    qa_pass_rate: float | None
    providers: list[ProviderRow]
    hooks: list[HookRow]
    gpu_hours: float


@dataclass(frozen=True)
class Arm:
    name: str
    videos: int
    good: int
    usd: float
    cost_per_video: float
    cost_per_good: float | None
    qa_score: float | None
    flagged: int
    rating: float | None
    retention_3s: float | None


def report(jobs: Iterable[Job], tariff: Tariff) -> Report:
    jobs = list(jobs)
    own = [c for j in jobs for c in j.calls if not c.shared]
    good = sum(j.good for j in jobs)
    failed = sum(j.status is Status.FAILED for j in jobs)
    usd = sum(c.usd for c in own)
    judged = [j.qa.score >= QA_PASS for j in jobs if j.qa]
    return Report(
        videos=len(jobs),
        good=good,
        failed=failed,
        pending=len(jobs) - good - failed,
        usd=usd,
        cost_per_good=usd / good if good else None,
        qa_pass_rate=fmean(judged) if judged else None,
        providers=_providers(own, tariff),
        hooks=_hooks(jobs),
        gpu_hours=sum(_gpu_seconds(tariff, c) for c in own) / 3600,
    )


def compare(jobs: Iterable[Job]) -> list[Arm]:
    arms: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        arms[j.arm or "-"].append(j)
    return [_arm(name, arms[name]) for name in sorted(arms)]


def _arm(name: str, jobs: list[Job]) -> Arm:
    usd = sum(j.cost for j in jobs)
    good = sum(j.good for j in jobs)
    own = [c for j in jobs for c in j.calls if not c.shared]
    return Arm(
        name=name,
        videos=len(jobs),
        good=good,
        usd=usd,
        cost_per_video=usd / len(jobs),
        cost_per_good=usd / good if good else None,
        qa_score=_mean([j.qa.score for j in jobs if j.qa]),
        flagged=sum(c.outcome is Outcome.FLAGGED for c in own),
        rating=_mean([float(j.rating) for j in jobs if j.rating is not None]),
        retention_3s=_mean([j.metrics.retention_3s for j in jobs if j.metrics]),
    )


def _providers(calls: list[Call], tariff: Tariff) -> list[ProviderRow]:
    grouped: dict[str, list[Call]] = defaultdict(list)
    for call in calls:
        grouped[call.provider].append(call)
    rows = [
        ProviderRow(
            provider=name,
            calls=len(made),
            flagged=sum(c.outcome is Outcome.FLAGGED for c in made),
            usd=sum(c.usd for c in made),
            gpu_hours=sum(_gpu_seconds(tariff, c) for c in made) / 3600,
        )
        for name, made in grouped.items()
    ]
    return sorted(rows, key=lambda r: r.gpu_hours, reverse=True)


def _hooks(jobs: list[Job]) -> list[HookRow]:
    grouped: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        if j.metrics and j.script:
            grouped[j.script.hook_kind].append(j)
    return [
        HookRow(
            kind=kind,
            videos=len(made),
            retention_3s=fmean(j.metrics.retention_3s for j in made if j.metrics),
            completion=fmean(j.metrics.completion for j in made if j.metrics),
        )
        for kind, made in sorted(grouped.items())
    ]


def _gpu_seconds(tariff: Tariff, call: Call) -> float:
    if call.outcome not in _COUNTED:
        return 0.0
    try:
        return tariff.gpu_seconds(call.provider, call.units)
    except KeyError:
        return 0.0


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None
