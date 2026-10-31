"""Download the weights listed in models.toml.

python scripts/fetch_models.py --models /models --hf-home /hf
python scripts/fetch_models.py --only video,music --with-optional
"""

import argparse
import os
import shutil
import tomllib
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


def main() -> None:
    args = _parse()
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    wanted = set(args.only.split(",")) if args.only else None

    def selected(entry: dict[str, object]) -> bool:
        if entry.get("optional") and not args.with_optional:
            return False
        return wanted is None or entry["stage"] in wanted

    for entry in filter(selected, manifest.get("file", [])):
        target = args.models / entry["into"] / Path(entry["path"]).name
        if target.exists():
            print(f"have  {target}")
            continue
        print(f"fetch {entry['repo']}/{entry['path']}  [{entry['license']}]")
        cached = hf_hub_download(entry["repo"], entry["path"], cache_dir=args.hf_home / "hub")
        target.parent.mkdir(parents=True, exist_ok=True)
        _place(Path(cached), target)

    for entry in filter(selected, manifest.get("snapshot", [])):
        print(f"fetch {entry['repo']}  [{entry['license']}]")
        snapshot_download(entry["repo"], cache_dir=args.hf_home / "hub")


def _place(cached: Path, target: Path) -> None:
    # A hard link costs no space when both folders sit on one disk; otherwise copy.
    try:
        os.link(cached.resolve(), target)
    except OSError:
        shutil.copy2(cached, target)


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=Path("models.toml"))
    parser.add_argument("--models", type=Path, default=Path("models"))
    parser.add_argument("--hf-home", type=Path, default=Path(os.environ.get("HF_HOME", "hf")))
    parser.add_argument("--only", help="comma-separated stages, e.g. video,music")
    parser.add_argument("--with-optional", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
