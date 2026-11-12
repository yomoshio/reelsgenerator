"""Destroys the rented vast.ai server once the queue is done or the balance runs low, after
the finished videos, the season plans and a database backup are safely on this computer.

    python3 scripts/autostop.py --set-key        store the API key from cloud.vast.ai/manage-keys
    python3 scripts/autostop.py --login          with two-factor login on: a code from the app
    python3 scripts/autostop.py --login --email  or a code vast sends to the account's email
    python3 scripts/autostop.py --dry-run --once one check, with every step but the destroy
    python3 scripts/autostop.py --dry-run --now  copy everything off now, destroy nothing
    scripts/remote.sh autostop                   watch in the background, log in logs/autostop.log

Runs here and not on the server: the files have to be copied off before it is gone. The
server is in scripts/remote.env (REMOTE_* and VAST_INSTANCE). A stopped vast instance still
bills for its disk, so the server is destroyed, not stopped. If anything fails to copy, or
vast refuses the key, the server stays and the log says so."""

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API = "https://console.vast.ai/api/v0"
CONFIG = Path.home() / ".config" / "vastai"
KEY = CONFIG / "vast_api_key"
SESSION = CONFIG / "vast_tfa_key"  # where the vast CLI keeps the key of a two-factor login
ROOT = Path(__file__).resolve().parent.parent
DONE = ("assembled", "approved", "published", "measured", "failed")
VIDEOS = "studio/output/reelsmith/videos"
REFUSED = (401, 403, 404)  # vast answers an expired session with 404


@dataclass(frozen=True)
class Reading:
    unfinished: int
    total: int
    credit: float | None
    usd_per_hour: float | None


def verdict(reading: Reading, quiet_checks: int, reserve_hours: float) -> str | None:
    """Why the server should go now, if it should. The queue counts as done only when it
    held jobs and stayed empty for two checks in a row, so a batch being queued is not
    mistaken for the end. Without a balance from vast only the queue decides."""
    credit, price = reading.credit, reading.usd_per_hour
    if credit is not None and price and credit / price < reserve_hours:
        return f"the balance ${credit:.2f} lasts {credit / price:.1f} h at this server's price"
    if reading.total and quiet_checks >= 2:
        return f"all {reading.total} jobs are finished"
    return None


def main() -> None:
    args = _parse()
    if args.set_key:
        _save(KEY, getpass.getpass("Vast API key: "))
        return
    if args.login:
        _login(email=args.email, code=args.code, secret=args.secret)
        return
    instance = _remote_env().get("VAST_INSTANCE") or sys.exit(
        "set VAST_INSTANCE in scripts/remote.env"
    )
    if args.now:
        _finish(instance, dry=args.dry_run)
        return
    quiet = 0
    while True:
        reading = _read(instance)
        quiet = quiet + 1 if reading.total and not reading.unfinished else 0
        reason = verdict(reading, quiet, args.reserve_hours)
        money = (
            f"balance ${reading.credit:.2f}, ${reading.usd_per_hour or 0:.3f}/h"
            if reading.credit is not None
            else "balance unknown"
        )
        _log(
            f"jobs left {reading.unfinished} of {reading.total}, {money}"
            + (f"; stopping: {reason}" if reason else "")
        )
        if reason:
            _finish(instance, dry=args.dry_run)
            return
        if args.once:
            return
        time.sleep(args.every)


def _read(instance: str) -> Reading:
    counts = _remote(
        "docker compose exec -T db psql -U reelsmith reelsmith -tAc "
        '"select status, count(*) from jobs group by status"'
    )
    by_status = {
        status: int(n)
        for status, n in (line.split("|") for line in counts.splitlines() if "|" in line)
    }
    credit = price = None
    try:
        credit = float(_vast("GET", "/users/current/").get("credit") or 0)
        server = _vast("GET", f"/instances/{instance}/?owner=me").get("instances") or {}
        price = float(server.get("dph_total") or 0)
    except urllib.error.HTTPError as exc:
        _log(f"vast refused the key ({exc.code}): {_why(exc)}")
    if credit is not None and not price:
        price = _local_price()
    return Reading(
        unfinished=sum(n for status, n in by_status.items() if status not in DONE),
        total=sum(by_status.values()),
        credit=credit,
        usd_per_hour=price,
    )


def _finish(instance: str, *, dry: bool) -> None:
    """Copies everything off the server, checks the copies, then destroys it."""
    _log("copying videos, season plans and a database backup")
    subprocess.run([ROOT / "scripts" / "remote.sh", "pull"], cwd=ROOT, check=True)
    backup = subprocess.run(
        [ROOT / "scripts" / "remote.sh", "backup"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[-1]
    if (ROOT / backup).stat().st_size < 1000:
        sys.exit(f"the backup {backup} is too small; the server stays")
    there = set(_remote(f"ls -1 {VIDEOS} 2>/dev/null || true").splitlines())
    here = {p.name for p in (ROOT / VIDEOS).glob("*")}
    if missing := there - here:
        sys.exit(f"not copied: {sorted(missing)}; the server stays")
    _log(f"copied {len(there)} videos and {backup}")
    if dry:
        _log(f"dry run: instance {instance} would be destroyed now")
        return
    try:
        _vast("DELETE", f"/instances/{instance}/", {})
    except urllib.error.HTTPError as exc:
        sys.exit(
            f"everything is copied, but vast refused to destroy instance {instance} "
            f"({exc.code}: {_why(exc)}). Destroy it at cloud.vast.ai/instances."
        )
    _log(f"instance {instance} destroyed")


def _login(*, email: bool, code: str | None, secret: str | None) -> None:
    """With two-factor login on, vast accepts the API key only together with a session
    from a code, and every later call goes with that session. An emailed code comes with a
    secret that goes back with it."""
    body: dict[str, object] = {"tfa_method": "totp"}
    if email:
        if not secret:
            secret = str(_vast("POST", "/tfa/email/", {}, key=_key(KEY))["secret"])
            print("vast sent a code to the account's email")
        body = {"tfa_method": "email", "secret": secret}
    body["code"] = (code or input("Code: ")).strip()
    reply = _vast("POST", "/tfa/", body, key=_key(KEY))
    session = reply.get("session_key")
    if not session:
        sys.exit(f"vast gave no session: {reply}")
    _save(SESSION, str(session))


def _vast(
    method: str, path: str, body: dict[str, object] | None = None, *, key: str | None = None
) -> dict[str, Any]:
    """A refused key passes the call to the next one: a two-factor session expires, and
    vast may then take the plain key again."""
    keys = [key] if key else _keys()
    for candidate in keys[:-1]:
        try:
            return _call(method, path, body, candidate)
        except urllib.error.HTTPError as exc:
            if exc.code not in REFUSED:
                raise
    return _call(method, path, body, keys[-1])


def _call(method: str, path: str, body: dict[str, object] | None, key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "reelsmith-autostop",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as reply:
        found: dict[str, Any] = json.load(reply)
        return found


def _keys() -> list[str]:
    found = [os.environ.get("VAST_API_KEY", "")]
    found += [path.read_text().strip() for path in (SESSION, KEY) if path.exists()]
    if keys := list(dict.fromkeys(k for k in found if k)):
        return keys
    sys.exit("no Vast API key: run python3 scripts/autostop.py --set-key")


def _key(path: Path) -> str:
    if path.exists() and (key := path.read_text().strip()):
        return key
    sys.exit("no Vast API key: run python3 scripts/autostop.py --set-key")


def _why(exc: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(exc.read()).get("msg", exc.reason))[:200]
    except ValueError:
        return str(exc.reason)


def _save(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.chmod(0o600)
    path.write_text(value.strip())
    print(f"saved to {path}")


def _remote(command: str) -> str:
    env = _remote_env()
    key = os.path.expanduser(os.path.expandvars(env.get("REMOTE_KEY") or "~/.ssh/id_ed25519"))
    reply = subprocess.run(
        [
            "ssh", "-i", key, "-p", env.get("REMOTE_PORT", "22"),
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", env["REMOTE_HOST"],
            f"cd {env.get('REMOTE_DIR', '/root/projects/reelsgenerator')} && {command}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )  # fmt: skip
    return reply.stdout


def _local_price() -> float | None:
    """The hourly price from .env, for a key that may read the balance but not the server."""
    path = ROOT / ".env"
    for line in path.read_text().splitlines() if path.exists() else ():
        if line.startswith("REELSMITH_GPU_HOUR_USD="):
            return float(line.split("=", 1)[1]) or None
    return None


def _remote_env() -> dict[str, str]:
    path = ROOT / "scripts" / "remote.env"
    if not path.exists():
        sys.exit("copy scripts/remote.env.example to scripts/remote.env")
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs if not k.lstrip().startswith("#")}


def _log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}", flush=True)


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--every", type=float, default=300, help="seconds between checks")
    parser.add_argument(
        "--reserve-hours", type=float, default=1.0, help="stop when the balance lasts less"
    )
    parser.add_argument("--dry-run", action="store_true", help="copy everything, destroy nothing")
    parser.add_argument("--once", action="store_true", help="one check, then exit")
    parser.add_argument("--now", action="store_true", help="copy everything off and stop now")
    parser.add_argument("--set-key", action="store_true", help="store the vast.ai API key")
    parser.add_argument("--login", action="store_true", help="two-factor login with a code")
    parser.add_argument("--code", help="the code for --login instead of asking")
    parser.add_argument("--email", action="store_true", help="--login with a code sent by email")
    parser.add_argument("--secret", help="--email: the secret of a code already sent")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, urllib.error.URLError, OSError) as exc:
        _log(f"stopped with an error, the server stays: {exc}")
        sys.exit(1)
