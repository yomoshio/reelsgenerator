import pytest

from reelsmith.models import Job, Outcome, StageError
from reelsmith.pricing import DEFAULT, RATES, Rate, Tariff, Unit, metered


def _job() -> Job:
    return Job.new("zombies")


def test_usd_is_gpu_time_at_the_hourly_rent() -> None:
    tariff = Tariff({"wan-2.2": Rate(Unit.SECOND, 48)}, usd_per_gpu_hour=0.99)

    assert tariff.gpu_seconds("wan-2.2", 5) == 240
    assert tariff.usd("wan-2.2", 5) == pytest.approx(0.066)


def test_rent_changes_without_touching_the_rates() -> None:
    doubled = Tariff(RATES, usd_per_gpu_hour=1.98)

    assert doubled.usd("wan-2.2", 1) == pytest.approx(2 * DEFAULT.usd("wan-2.2", 1))


def test_tariff_rejects_unknown_provider() -> None:
    with pytest.raises(KeyError, match="veo"):
        Tariff({}).usd("veo", 1)


def test_default_tariff_covers_the_local_stack() -> None:
    assert set(RATES) == {
        "ollama",
        "z-image",
        "qwen-edit",
        "wan-2.2",
        "wan-2.2-hd",
        "wan-5b",
        "still",
        "voxcpm",
        "qwen3-tts",
        "ace-step",
    }
    assert DEFAULT.gpu_seconds("wan-2.2", 5) == 70


def test_metered_records_ok_call_with_price() -> None:
    job = _job()
    tariff = Tariff({"wan-2.2": Rate(Unit.SECOND, 3600)}, usd_per_gpu_hour=0.99)

    with metered(job, tariff, stage="animate", provider="wan-2.2", units=5, shot=2):
        pass

    (call,) = job.calls
    assert (call.stage, call.provider, call.units, call.shot) == ("animate", "wan-2.2", 5, 2)
    assert call.usd == pytest.approx(4.95)
    assert call.outcome is Outcome.OK
    assert call.seconds >= 0


def test_metered_marks_errors_failed_and_reraises() -> None:
    job = _job()
    tariff = Tariff({"wan-2.2": Rate(Unit.SECOND, 48)})

    with (
        pytest.raises(StageError),
        metered(job, tariff, stage="animate", provider="wan-2.2", units=5),
    ):
        raise StageError("comfy: 502")

    assert job.calls[0].outcome is Outcome.FAILED


def test_caller_can_flag_the_call_afterwards() -> None:
    job = _job()
    tariff = Tariff({"fast": Rate(Unit.SECOND, 1)})

    with metered(job, tariff, stage="animate", provider="fast", units=4) as call:
        pass
    call.outcome = Outcome.FLAGGED

    assert job.calls[0].outcome is Outcome.FLAGGED
