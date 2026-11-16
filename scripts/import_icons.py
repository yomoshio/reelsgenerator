"""Fills the thing library with the silhouettes of game-icons.net: about four thousand
objects, people's tools, furniture, jewellery, vehicles, buildings, as flat single-colour
SVGs the runtime recolours to the style's palette.

    python scripts/import_icons.py                  into library/things
    python scripts/import_icons.py --zip icons.zip  from an archive already downloaded

The icons are CC BY 3.0 (a few CC0): a video that shows one names its author in post.txt,
which the assemble step does from library/things/index.json. Every icon comes with a black
square behind it; that square is cut, so only the object is left."""

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE = "https://codeload.github.com/game-icons/icons/zip/refs/heads/master"
BACKGROUND = re.compile(r'<path d="M0 0h512v512H0z"\s*/>')
CC0 = {"viscious-speed", "zeromancer"}


def name_of(path: str) -> str:
    return Path(path).stem.replace("-", "_")


def clean(svg: str) -> str:
    """The icon without its square, drawn in black so the runtime can recolour it."""
    svg = BACKGROUND.sub("", svg, count=1)
    return svg.replace('fill="#fff"', 'fill="#000"')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--out", type=Path, default=Path("library/things"))
    args = parser.parse_args()
    raw = args.zip.read_bytes() if args.zip else urllib.request.urlopen(ARCHIVE, timeout=120).read()
    args.out.mkdir(parents=True, exist_ok=True)
    index_file = args.out / "index.json"
    index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.is_file() else {}
    added = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in sorted(archive.namelist()):
            parts = entry.split("/")
            if len(parts) != 3 or not entry.endswith(".svg"):
                continue
            author, name = parts[1], name_of(entry)
            if name in index:
                continue
            (args.out / f"{name}.svg").write_text(
                clean(archive.read(entry).decode("utf-8")), encoding="utf-8"
            )
            index[name] = {
                "about": name.replace("_", " "),
                "author": author,
                "license": "CC0" if author in CC0 else "CC BY 3.0",
                "source": "game-icons.net",
            }
            added += 1
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{added} things added, {len(index)} in {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
