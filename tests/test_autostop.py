import gzip
import importlib.util
import io
import urllib.error
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


def test_an_expired_session_hands_the_call_to_the_plain_key(
    autostop: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "session").write_text("old-session\n")
    (tmp_path / "key").write_text("plain-key\n")
    monkeypatch.setattr(autostop, "SESSION", tmp_path / "session")
    monkeypatch.setattr(autostop, "KEY", tmp_path / "key")
    monkeypatch.delenv("VAST_API_KEY", raising=False)
    tried: list[str] = []

    def urlopen(request: object, timeout: float) -> io.BytesIO:
        key = request.get_header("Authorization")  # type: ignore[attr-defined]
        tried.append(key)
        if key == "Bearer old-session":
            raise urllib.error.HTTPError("u", 404, "Session expired", {}, None)  # type: ignore[arg-type]
        return io.BytesIO(b'{"credit": 2.55}')

    monkeypatch.setattr(autostop.urllib.request, "urlopen", urlopen)

    assert autostop._vast("GET", "/users/current/") == {"credit": 2.55}
    assert tried == ["Bearer old-session", "Bearer plain-key"]


def test_a_refusal_of_the_last_key_reaches_the_caller(
    autostop: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autostop, "SESSION", tmp_path / "none")
    monkeypatch.setenv("VAST_API_KEY", "only-key")

    def urlopen(request: object, timeout: float) -> io.BytesIO:
        raise urllib.error.HTTPError("u", 401, "no", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(autostop.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(autostop, "KEY", tmp_path / "none")

    with pytest.raises(urllib.error.HTTPError):
        autostop._vast("GET", "/users/current/")


def test_a_box_with_nothing_to_do_goes_after_the_idle_checks(autostop: ModuleType) -> None:
    empty = autostop.Reading(unfinished=0, total=0, credit=20.0, usd_per_hour=0.87)
    working = autostop.Reading(unfinished=0, total=0, credit=20.0, usd_per_hour=0.87, busy=True)
    unread = autostop.Reading(unfinished=None, total=None, credit=20.0, usd_per_hour=0.87)

    assert autostop.verdict(empty, 0, 1.0, idle_checks=11, most=12) is None
    assert autostop.verdict(empty, 0, 1.0, idle_checks=12, most=12) == (
        "nothing has run for 12 checks in a row"
    )
    assert autostop.verdict(empty, 0, 1.0, idle_checks=99, most=0) is None
    assert empty.idle
    assert unread.idle
    assert not working.idle


def test_a_backup_counts_when_pg_dump_finished_it_whatever_its_size(
    autostop: ModuleType, tmp_path: Path
) -> None:
    whole, cut = tmp_path / "whole.sql.gz", tmp_path / "cut.sql.gz"
    whole.write_bytes(gzip.compress(b"--\n-- PostgreSQL database dump complete\n--\n"))
    cut.write_bytes(gzip.compress(b"COPY public.jobs (id) FROM stdin;\n"))

    assert autostop.dumped(whole)
    assert not autostop.dumped(cut)
    assert not autostop.dumped(tmp_path / "missing.sql.gz")
