"""Copies a job as it stood after a step, under a new id, so the same story can be staged
by another model or in another mode and the two compared.

    python tools/variant.py jobs/1124-771ff1 "coder devstral"            a copy with its voice
    python tools/variant.py jobs/1124-771ff1 "voice qwen" --at written   a copy to be read anew

The label goes into the job's title; tools/compare.py prints it."""

import argparse
import shutil
from pathlib import Path

from reelsmith.jobs import Job, Jobs, Source, Status, forget


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("job", type=Path)
    parser.add_argument("label")
    parser.add_argument("--at", default="voiced", choices=["new", "written", "voiced", "staged"])
    args = parser.parse_args()
    old = Job.model_validate_json((args.job / "job.json").read_text(encoding="utf-8"))
    jobs = Jobs(args.job.parent)
    title = f"{old.source.title or old.id} · {args.label}"
    new = jobs.create(Source(kind=old.source.kind, text=old.source.text, title=title), old.style)
    folder = jobs.folder(new)
    shutil.copytree(args.job, folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("job.json"))
    forget(folder, Status(args.at))
    (folder / "graph.json").unlink(missing_ok=True)
    new.status = Status(args.at)
    jobs.save(new)
    print(new.id)


if __name__ == "__main__":
    main()
