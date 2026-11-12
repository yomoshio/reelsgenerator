"""Download the weights listed in models.toml.

python scripts/fetch_models.py --models models --hf-home hf
python scripts/fetch_models.py --only video,music --with-optional

Both folders must sit on one mount, so a weight in models/ is a hard link into the cache
and not a second copy; `./run.sh models` mounts the project once for that.

Entries come from Hugging Face (`file`, `snapshot`) or from a plain address (`url`), for
weights that only live in a GitHub release.
"""

import argparse
import os
import shutil
import tomllib
import urllib.request
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download, try_to_load_from_cache


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
            _relink(entry["repo"], entry["path"], target, args.hf_home / "hub")
            print(f"have  {target}")
            continue
        print(f"fetch {entry['repo']}/{entry['path']}  [{entry['license']}]")
        cached = hf_hub_download(entry["repo"], entry["path"], cache_dir=args.hf_home / "hub")
        target.parent.mkdir(parents=True, exist_ok=True)
        _place(Path(cached), target)

    for entry in filter(selected, manifest.get("snapshot", [])):
        print(f"fetch {entry['repo']}  [{entry['license']}]")
        snapshot_download(entry["repo"], cache_dir=args.hf_home / "hub")

    for entry in filter(selected, manifest.get("url", [])):
        target = args.models / entry["into"] / entry["url"].rsplit("/", 1)[-1]
        if target.exists():
            print(f"have  {target}")
            continue
        print(f"fetch {entry['url']}  [{entry['license']}]")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        urllib.request.urlretrieve(entry["url"], partial)
        partial.rename(target)


def _place(cached: Path, target: Path) -> None:
    # A hard link costs no space when both folders sit on one mount; otherwise copy.
    try:
        os.link(cached.resolve(), target)
    except OSError:
        shutil.copy2(cached, target)


def _relink(repo: str, path: str, target: Path, cache: Path) -> None:
    """Earlier installs mounted the weights and the cache separately, so every file was
    copied and sat on the disk twice. Pointing the cached copy at the target frees that."""
    cached = try_to_load_from_cache(repo, path, cache_dir=cache)
    if not isinstance(cached, str):
        return
    blob = Path(cached).resolve()
    if blob.samefile(target) or blob.stat().st_size != target.stat().st_size:
        return
    spare = blob.with_name(blob.name + ".link")
    try:
        os.link(target, spare)
    except OSError:
        return
    os.replace(spare, blob)
    print(f"freed {target.stat().st_size / 2**30:.1f} GB: {target.name} is no longer kept twice")


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
