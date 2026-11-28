"""Rents a vast.ai server for the models and writes its address into .env.

    python3 scripts/rent.py --dry-run             show the offer that would be taken
    python3 scripts/rent.py                       take the cheapest one that fits
    python3 scripts/rent.py --vram 46 --price 1   a smaller card, at most $1 an hour
    ./run.sh box rent                             the same, then ./run.sh box install

Only virtual machines are taken: the models run in Docker, and Docker does not run inside a
vast container. The site lists few of them; the API lists them all. The key is the one
scripts/autostop.py uses. Billing starts when the server does, so the next command is
./run.sh box install, which starts the watcher that destroys an idle server."""

import argparse
import re
import socket
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autostop

IMAGE = "docker.io/vastai/kvm:cuda-12.9.1-auto"  # Ubuntu 22.04 with the NVIDIA driver in
BOOT_SECONDS = 1200
# Some hosts bill every gigabyte downloaded; at $0.04 the weights cost more than a day of the card.
TRAFFIC = 0.003  # dollars a GB, at most


def offers(vram: float, price: float, disk: int) -> list[dict[str, Any]]:
    query = {
        "verified": {"eq": True}, "rentable": {"eq": True}, "rented": {"eq": False},
        "vms_enabled": {"eq": True}, "num_gpus": {"eq": 1}, "gpu_ram": {"gte": vram * 1000},
        "disk_space": {"gte": disk}, "inet_down": {"gte": 300}, "reliability2": {"gte": 0.97},
        "dph_total": {"lte": price}, "type": "on-demand", "allocated_storage": disk,
        "order": [["dph_total", "asc"]], "limit": 50,
    }  # fmt: skip
    found: list[dict[str, Any]] = autostop._vast("POST", "/bundles/", query).get("offers", [])
    return [o for o in found if o.get("vms_enabled") and (o.get("inet_down_cost") or 0) <= TRAFFIC]


def told(offer: dict[str, Any]) -> str:
    return (
        f"{offer['gpu_name']} {offer['gpu_ram'] / 1024:.0f} GB, ${offer['dph_total']:.2f}/h, "
        f"{offer['cpu_cores_effective']:.0f} cores, {offer['cpu_ram'] / 1024:.0f} GB RAM, "
        f"{offer.get('geolocation') or 'somewhere'}, offer {offer['id']}"
    )


def rent(offer: dict[str, Any], disk: int) -> str:
    body = {"client_id": "me", "image": IMAGE, "disk": disk, "label": "reelsmith",
            "runtype": "ssh_direct", "env": {}, "onstart": ""}  # fmt: skip
    reply = autostop._vast("PUT", f"/asks/{offer['id']}/", body)
    if not reply.get("success"):
        sys.exit(f"vast did not rent offer {offer['id']}: {reply.get('msg') or reply}")
    return str(reply["new_contract"])


def answers(host: str, port: int) -> bool:
    """Whether an SSH server greets on this port: the VM has booted, not only been mapped."""
    try:
        with socket.create_connection((host, port), timeout=10) as link:
            link.settimeout(10)
            return link.recv(4).startswith(b"SSH")
    except OSError:
        return False


def address(instance: str) -> tuple[str, str]:
    """Waits for the server to start and gives its address and SSH port."""
    until = time.time() + BOOT_SECONDS
    while time.time() < until:
        server = autostop._vast("GET", f"/instances/{instance}/?owner=me").get("instances") or {}
        ports = (server.get("ports") or {}).get("22/tcp") or []
        # A virtual machine can stay "created" in vast's eyes while it is already up, so the
        # open SSH port is what says it has started.
        if ports and server.get("public_ipaddr"):
            host, port = str(server["public_ipaddr"]).strip(), str(ports[0]["HostPort"])
            if answers(host, int(port)):
                return host, port
        time.sleep(15)
    sys.exit(
        f"server {instance} did not start in {BOOT_SECONDS // 60} minutes; it is still rented: "
        "look at cloud.vast.ai/instances and destroy it there if it stays down"
    )


def remember(instance: str, host: str, port: str) -> None:
    path = autostop.ROOT / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for name, value in (
        ("SERVER_HOST", f"root@{host}"), ("SERVER_PORT", port), ("VAST_INSTANCE", instance)
    ):  # fmt: skip
        line = f"{name}={value}"
        if re.search(rf"^{name}=.*$", text, flags=re.M):
            text = re.sub(rf"^{name}=.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--vram", type=float, default=80, help="GB of video memory, at least")
    parser.add_argument("--price", type=float, default=2.5, help="dollars an hour, at most")
    parser.add_argument("--disk", type=int, default=150, help="GB of disk")
    parser.add_argument("--dry-run", action="store_true", help="show the offer, rent nothing")
    args = parser.parse_args()
    try:
        found = offers(args.vram, args.price, args.disk)
        credit = float(autostop._vast("GET", "/users/current/").get("credit") or 0)
    except urllib.error.HTTPError as exc:
        sys.exit(f"vast refused the key ({exc.code}): {autostop._why(exc)}")
    if not found:
        sys.exit(
            f"no virtual machine with {args.vram:.0f} GB under ${args.price}/h right now; "
            "raise --price or lower --vram"
        )
    offer = found[0]
    hours = credit / offer["dph_total"]
    print(f"{told(offer)}\nbalance ${credit:.2f}: {hours:.1f} h of it")
    if args.dry_run:
        return
    if hours < 1.5:
        sys.exit("the balance lasts under an hour and a half: top it up at cloud.vast.ai/billing")
    instance = rent(offer, args.disk)
    print(f"rented, server {instance}; waiting for it to start")
    host, port = address(instance)
    remember(instance, host, port)
    print(f"root@{host} port {port} is in .env; next: ./run.sh box install")


if __name__ == "__main__":
    main()
