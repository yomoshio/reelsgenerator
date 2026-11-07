import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "autostop.py"


@pytest.fixture(scope="module")
def autostop() -> ModuleType:
    spec = importlib.util.spec_from_file_location("autostop", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_server_goes_when_the_balance_would_not_last_the_reserve(autostop: ModuleType) -> None:
    low = autostop.Reading(unfinished=4, total=6, credit=1.5, usd_per_hour=1.958)
    enough = autostop.Reading(unfinished=4, total=6, credit=20.0, usd_per_hour=1.958)

    assert autostop.verdict(low, 0, reserve_hours=1.0) == (
        "the balance $1.50 lasts 0.8 h at this server's price"
    )
    assert autostop.verdict(enough, 0, reserve_hours=1.0) is None


def test_the_queue_counts_as_done_only_after_two_quiet_checks_of_a_queue_that_held_jobs(
    autostop: ModuleType,
) -> None:
    done = autostop.Reading(unfinished=0, total=11, credit=None, usd_per_hour=None)
    never = autostop.Reading(unfinished=0, total=0, credit=None, usd_per_hour=None)

    assert autostop.verdict(done, 1, reserve_hours=1.0) is None
    assert autostop.verdict(done, 2, reserve_hours=1.0) == "all 11 jobs are finished"
    assert autostop.verdict(never, 5, reserve_hours=1.0) is None
