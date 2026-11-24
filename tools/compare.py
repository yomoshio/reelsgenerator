"""One line a job: how long each step took and how its beats were staged.

    python tools/compare.py jobs/1124-*            every job of the day
    python tools/compare.py jobs/a jobs/b --price 0.86   with the cost at this price an hour

sheet: beats staged from a sheet, with the rounds they took; coder: beats the coder wrote,
those clean at the first try, and those that fell back to the plain scene."""

import argparse
import json
from pathlib import Path

STEPS = ["write", "voice", "stage", "render", "assemble"]


def row(folder: Path, price: float) -> dict[str, str]:
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    took = dict.fromkeys(STEPS, 0.0)
    for entry in job.get("log", []):
        if entry["step"] in took and not str(entry.get("note", "")).startswith("failed"):
            took[entry["step"]] = entry["seconds"]
    beats = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("scenes/beat*.json"))
    ]
    sheets = [b for b in beats if b.get("sheet")]
    coded = [b for b in beats if not b.get("sheet")]
    clean = sum(1 for b in coded if b["rounds"] == 1 and not b["fallback"] and not b["left"])
    total = sum(took.values())
    out = {
        "job": job["id"],
        "what": (job["source"].get("title") or "")[:34],
        "status": job["status"],
        **{s: f"{took[s] / 60:.1f}" for s in STEPS},
        "min": f"{total / 60:.1f}",
        "beats": str(len(beats)),
        "sheet": f"{len(sheets)} ({sum(b['rounds'] for b in sheets)}r)" if sheets else "-",
        "coder": f"{len(coded)} ({clean} clean, {sum(1 for b in coded if b['fallback'])} plain)"
        if coded
        else "-",
        "left": str(sum(len(b.get("left") or []) for b in beats)),
    }
    if price:
        out["$"] = f"{total / 3600 * price:.2f}"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("jobs", type=Path, nargs="+")
    parser.add_argument("--price", type=float, default=0.0, help="dollars an hour of the server")
    args = parser.parse_args()
    rows = [row(f, args.price) for f in args.jobs if (f / "job.json").is_file()]
    if not rows:
        return
    widths = {k: max(len(k), *(len(r[k]) for r in rows)) for k in rows[0]}
    print("  ".join(k.ljust(widths[k]) for k in rows[0]))
    for r in rows:
        print("  ".join(r[k].ljust(widths[k]) for k in r))


if __name__ == "__main__":
    main()
