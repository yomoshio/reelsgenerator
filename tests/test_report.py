import pytest

from reelsmith.models import Call, Job, Metrics, Outcome, Status, Verdict
from reelsmith.pricing import DEFAULT
from reelsmith.report import compare, report
from tests.fakes import job, recipe, script, tariff


def _paid(status: Status, usd: float = 4.0, provider: str = "fast") -> Job:
    made = job(status=status, script=script())
    made.calls.append(Call(stage="animate", provider=provider, units=1, usd=usd))
    return made


def test_cost_per_good_video_includes_failed_spend() -> None:
    jobs = [_paid(Status.APPROVED), _paid(Status.PUBLISHED), _paid(Status.FAILED)]

    made = report(jobs, tariff())

    assert (made.videos, made.good, made.failed, made.pending) == (3, 2, 1, 0)
    assert made.usd == pytest.approx(12.0)
    assert made.cost_per_good == pytest.approx(6.0)


def test_report_without_good_videos_has_no_cost_per_good() -> None:
    made = report([_paid(Status.ASSEMBLED)], tariff())

    assert made.cost_per_good is None
    assert made.pending == 1


def test_report_does_not_count_shared_calls_twice() -> None:
    parent = _paid(Status.FRAMED)
    child = parent.fork(recipe(video="slow"), "B")
    child.calls.append(Call(stage="animate", provider="slow", units=1, usd=2.0))

    assert report([parent, child], tariff()).usd == pytest.approx(6.0)
    arms = {a.name: a for a in compare([parent, child])}
    assert arms["A"].usd == pytest.approx(4.0)
    assert arms["B"].usd == pytest.approx(6.0)


def test_provider_rows_carry_flag_rate_and_gpu_hours() -> None:
    made = job(status=Status.FAILED)
    made.calls += [Call(stage="animate", provider="wan-2.2", units=5, usd=0.066)] * 4
    made.calls.append(
        Call(stage="animate", provider="wan-2.2", units=5, usd=0.066, outcome=Outcome.FLAGGED)
    )
    made.calls += [Call(stage="frame", provider="z-image", units=1, usd=0.003)] * 2

    rows = {r.provider: r for r in report([made], DEFAULT).providers}

    assert (rows["wan-2.2"].calls, rows["wan-2.2"].flagged) == (5, 1)
    assert rows["wan-2.2"].flag_rate == pytest.approx(0.2)
    assert rows["wan-2.2"].gpu_hours == pytest.approx(5 * 240 / 3600)
    assert rows["z-image"].gpu_hours == pytest.approx(20 / 3600)
    assert [r.provider for r in report([made], DEFAULT).providers] == ["wan-2.2", "z-image"]


def test_gpu_hours_skip_calls_that_produced_nothing() -> None:
    made = job(status=Status.APPROVED)
    made.calls += [Call(stage="animate", provider="wan-2.2", units=10, usd=0.13)] * 2
    made.calls.append(
        Call(stage="animate", provider="wan-2.2", units=10, usd=0.13, outcome=Outcome.FAILED)
    )

    assert report([made], DEFAULT).gpu_hours == pytest.approx(960 / 3600)


def test_qa_pass_rate_counts_judged_jobs_only() -> None:
    passed, failed, unjudged = job(status=Status.APPROVED), job(status=Status.FAILED), job()
    passed.qa = Verdict(score=8.0)
    failed.qa = Verdict(score=5.0)

    assert report([passed, failed, unjudged], tariff()).qa_pass_rate == pytest.approx(0.5)
    assert report([unjudged], tariff()).qa_pass_rate is None


def _measured(kind: str, retention: float) -> Job:
    made = job(status=Status.MEASURED, script=script(hook_kind=kind))
    made.metrics = Metrics(views=1000, retention_3s=retention, completion=retention / 2)
    return made


def test_retention_is_averaged_per_hook_kind() -> None:
    jobs = [_measured("question", 0.5), _measured("question", 0.7), _measured("threat", 0.3)]

    rows = {r.kind: r for r in report(jobs, tariff()).hooks}

    assert (rows["question"].videos, rows["question"].retention_3s) == (2, pytest.approx(0.6))
    assert rows["question"].completion == pytest.approx(0.3)
    assert (rows["threat"].videos, rows["threat"].retention_3s) == (1, pytest.approx(0.3))


def test_compare_groups_arms() -> None:
    a1, a2, b, loose = (
        _paid(Status.APPROVED, 3.0),
        _paid(Status.FAILED, 5.0),
        _paid(Status.APPROVED, 2.0, "slow"),
        _paid(Status.NEW, 1.0),
    )
    a1.arm = a2.arm = "A"
    b.arm = "B"
    a1.rating, a2.rating = 8, 6
    a1.qa, a2.qa = Verdict(score=8.0), Verdict(score=9.0)
    a1.metrics = Metrics(views=10, retention_3s=0.4, completion=0.2)

    arms = {arm.name: arm for arm in compare([a1, a2, b, loose])}

    assert [arm.name for arm in compare([a1, a2, b, loose])] == ["-", "A", "B"]
    assert (arms["A"].videos, arms["A"].good) == (2, 1)
    assert arms["A"].usd == pytest.approx(8.0)
    assert arms["A"].cost_per_video == pytest.approx(4.0)
    assert arms["A"].cost_per_good == pytest.approx(8.0)
    assert arms["A"].qa_score == pytest.approx(8.5)
    assert arms["A"].rating == pytest.approx(7.0)
    assert arms["A"].retention_3s == pytest.approx(0.4)
    assert (arms["B"].rating, arms["B"].qa_score, arms["B"].cost_per_good) == (None, None, 2.0)
    assert arms["-"].videos == 1
