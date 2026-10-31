"""What a call costs: GPU seconds per unit, and dollars at the hourly rent.

The seconds were measured on an RTX 4090 48 GB with the graphs in workflows/ and the
defaults in settings.py, model loading excluded. `wan-5b` is not measured yet; `still`
runs on the CPU and costs no GPU time. A different
card or bigger clips change them; the time of each prompt is in ComfyUI's queue panel."""

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from reelsmith.models import Call, Job, Outcome

GPU_HOUR_USD = 0.99


class Unit(StrEnum):
    CALL = "call"
    IMAGE = "image"
    SECOND = "second"
    CHAR = "char"


@dataclass(frozen=True, slots=True)
class Rate:
    unit: Unit
    gpu_seconds: float


RATES: Mapping[str, Rate] = {
    "ollama": Rate(Unit.CALL, 15),
    "z-image": Rate(Unit.IMAGE, 4),
    "wan-2.2": Rate(Unit.SECOND, 14),
    "wan-5b": Rate(Unit.SECOND, 6),
    "voxcpm": Rate(Unit.CHAR, 0.07),
    "still": Rate(Unit.SECOND, 0),
    "ace-step": Rate(Unit.SECOND, 2),
}


class Tariff:
    def __init__(
        self, rates: Mapping[str, Rate], *, usd_per_gpu_hour: float = GPU_HOUR_USD
    ) -> None:
        self._rates = dict(rates)
        self._hourly = usd_per_gpu_hour

    def rate(self, provider: str) -> Rate:
        try:
            return self._rates[provider]
        except KeyError:
            raise KeyError(f"no tariff for provider {provider!r}") from None

    def gpu_seconds(self, provider: str, units: float) -> float:
        return self.rate(provider).gpu_seconds * units

    def usd(self, provider: str, units: float) -> float:
        return self.gpu_seconds(provider, units) / 3600 * self._hourly


DEFAULT = Tariff(RATES)


@contextmanager
def metered(
    job: Job,
    tariff: Tariff,
    *,
    stage: str,
    provider: str,
    units: float = 1.0,
    shot: int | None = None,
) -> Iterator[Call]:
    """Records the call whatever happens inside, so failed attempts cost GPU time too."""
    call = Call(
        stage=stage, provider=provider, units=units, usd=tariff.usd(provider, units), shot=shot
    )
    started = time.perf_counter()
    try:
        yield call
    except Exception:
        call.outcome = Outcome.FAILED
        raise
    finally:
        call.seconds = round(time.perf_counter() - started, 3)
        job.calls.append(call)
