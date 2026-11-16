"""Turns a picture of one thing into a flat silhouette in the thing library, for things the
library does not have: a ball gown, a carriage of 1880, a particular cash machine. Draw
the thing once with any image model, on a plain light background, look at the result, and
it is drawn by code from then on, the same in every video.

    pip install vtracer
    python scripts/vectorize.py gown.png ball_gown "a ball gown of the 1880s"

The background is dropped by brightness, the rest becomes one black shape the runtime
recolours to the style's palette."""

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps


def silhouette(image: Path, out: Path, threshold: int = 200) -> None:
    """A black and white PNG: the thing black, the background white."""
    grey = ImageOps.grayscale(Image.open(image))
    grey.point(lambda v: 0 if v < threshold else 255).save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("name", help="the thing's name in lower case with underscores")
    parser.add_argument("about", help="what it is, in English, for the director")
    parser.add_argument("--library", type=Path, default=Path("library/things"))
    parser.add_argument("--threshold", type=int, default=200)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.name):
        sys.exit("the name is lower case latin letters, digits and underscores")
    try:
        import vtracer  # noqa: PLC0415 - only this script needs it
    except ImportError:
        sys.exit("pip install vtracer")
    args.library.mkdir(parents=True, exist_ok=True)
    out = args.library / f"{args.name}.svg"
    with tempfile.TemporaryDirectory() as tmp:
        flat = Path(tmp) / "flat.png"
        silhouette(args.image, flat, args.threshold)
        vtracer.convert_image_to_svg_py(str(flat), str(out), colormode="binary")
    svg = out.read_text(encoding="utf-8")
    svg = re.sub(r'<path[^>]*fill="#(?:fff|FFF|ffffff|FFFFFF)"[^>]*/>', "", svg)
    out.write_text(svg, encoding="utf-8")
    index_file = args.library / "index.json"
    index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.is_file() else {}
    index[args.name] = {"about": args.about, "license": "CC0", "source": str(args.image.name)}
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
