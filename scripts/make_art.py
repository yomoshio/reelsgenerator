"""Pictures for a series library, drawn by Z-Image through ComfyUI: a background for every
location and a figure for every pose, in several takes each. A take becomes the library's
picture once --pick copies it; graphics.py then draws it in place of its stand-in.

    ./run.sh server comfy                          # the server's ComfyUI on localhost:8188
    python scripts/make_art.py studio/series/flood --takes 4
    python scripts/make_art.py studio/series/flood --only locations --takes 6
    python scripts/make_art.py studio/series/flood --pick flat=2 stand=1

Takes land in <series>/art/: locations/<key>-<n>.png, poses/<key>-<n>.png, and a sheet for
each kind. The location sheet marks every anchor on every take, to see whether the picture
puts the window where the beats point at it; the pose sheet shows each figure on its scene.
Who the figures are comes from the [art] table of library.toml, which the beats ignore:

    [art]
    hero = "a thin boy of fifteen in a grey hoodie"
"""

import argparse
import asyncio
import shutil
import tomllib
import zlib
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from reelsmith.beats import Anchor, Library, Location, read_library
from reelsmith.graphics import HERO_HEIGHT, SCENE_BOTTOM, H, W, at, font, scene
from reelsmith.services.comfy import ComfyClient, ComfyPainter, Workflow

ROOT = Path(__file__).resolve().parent.parent
PAINT = (1088, 1920)  # Z-Image wants sides divisible by 16; the 8 extra columns are cut off
FIGURE = (768, 1152)
BACKDROP = "plain flat light grey background, nothing else on it"
THUMB = (270, 480)


def where(anchor: Anchor) -> str:
    """The place of an anchor in words, for a model that cannot take coordinates."""
    side = (
        "on the left" if anchor.x < 0.36 else "on the right" if anchor.x > 0.64 else "in the middle"
    )
    height = anchor.y / (SCENE_BOTTOM / H)
    level = (
        "high up" if height < 0.45 else "at mid height" if height < 0.75 else "low, at floor level"
    )
    return f"{side}, {level}"


def location_prompt(location: Location, look: str) -> str:
    things = [
        f"{anchor.about or name.replace('_', ' ')} {where(anchor)}"
        for name, anchor in location.anchors.items()
        if name not in ("hero", "companion")
    ]
    layout = "; ".join(things)
    return (
        f"{look.strip()}. {location.about} Layout: {layout}. The scene fills the top sixty "
        "percent of the picture; the bottom forty percent is plain dark floor in shadow, empty."
    )


def pose_prompt(pose: str, who: str, look: str) -> str:
    return (
        f"flat vector illustration, simple flat shapes, no texture. One small featureless "
        f"figure, full body from head to feet, {who}, {pose}. Dark muted clothes, no face "
        f"details. {BACKDROP}. No shadow on the ground, no text. Same art as: {look.strip()}"
    )


def keyed(picture: Image.Image, tolerance: int = 38) -> Image.Image:
    """The figure cut out of its flat backdrop: the backdrop is the colour of the edges, and
    only the part of it that reaches the edges goes, so a grey shirt keeps its colour."""
    rgb = picture.convert("RGB")
    w, h = rgb.size
    edges = Image.new("RGB", (2 * w + 2 * h, 4))
    for i, strip in enumerate(
        (rgb.crop((0, 0, w, 4)), rgb.crop((0, h - 4, w, h)),
         rgb.crop((0, 0, 4, h)).rotate(90, expand=True),
         rgb.crop((w - 4, 0, w, h)).rotate(90, expand=True))
    ):  # fmt: skip
        edges.paste(strip, (sum((w, w, h)[:i]), 0))
    backdrop = tuple(round(v) for v in ImageStat.Stat(edges).median)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, backdrop)).convert("L")
    mask = diff.point(lambda v: 255 if v > tolerance else 0)
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if mask.getpixel(corner) == 0:
            ImageDraw.floodfill(mask, corner, 128)
    alpha = mask.point(lambda v: 0 if v == 128 else 255).filter(ImageFilter.MinFilter(3))
    out = rgb.convert("RGBA")
    out.putalpha(alpha.filter(ImageFilter.GaussianBlur(1)))
    return out


def figure(picture: Image.Image, height: int = HERO_HEIGHT) -> Image.Image:
    """Cut out, cropped to the figure and scaled to the hero's height, feet at the bottom."""
    cut = keyed(picture)
    box = cut.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
    if box is None:
        raise ValueError("nothing left after the backdrop was cut out")
    cut = cut.crop(box)
    return cut.resize(
        (max(1, round(cut.width * height / cut.height)), height), Image.Resampling.LANCZOS
    )


def location_sheet(takes: dict[str, list[Path]], library: Library) -> Image.Image:
    rows = list(takes.items())
    cols = max(len(paths) for _, paths in rows)
    tw, th = THUMB
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, len(rows) * (th + 50) + 10), (8, 8, 8))
    d = ImageDraw.Draw(sheet)
    small = font(18)
    for r, (key, paths) in enumerate(rows):
        y0 = 10 + r * (th + 50)
        d.text((10, y0), key, font=small, fill=(255, 255, 255))
        for c, path in enumerate(paths):
            x0 = 10 + c * (tw + 10)
            sheet.paste(Image.open(path).convert("RGB").resize(THUMB), (x0, y0 + 30))
            d.text((x0 + 4, y0 + 34), path.stem.rsplit("-", 1)[1], font=small, fill=(255, 210, 31))
            line = y0 + 30 + th * SCENE_BOTTOM / H
            d.line((x0, line, x0 + tw, line), fill=(120, 120, 120))
            for name, anchor in library.locations[key].anchors.items():
                ax, ay = x0 + anchor.x * tw, y0 + 30 + anchor.y * th
                d.ellipse((ax - 5, ay - 5, ax + 5, ay + 5), outline=(255, 60, 60), width=2)
                d.text((ax + 7, ay - 9), name, font=font(13), fill=(255, 90, 90))
    return sheet


def pose_sheet(takes: dict[str, list[Path]], library: Library, folder: Path) -> Image.Image:
    key, location = next(iter(library.locations.items()))
    stage = scene(key, location, folder).convert("RGB")
    feet = at(location.anchors["hero"])
    tw, th = THUMB
    rows = list(takes.items())
    cols = max(len(paths) for _, paths in rows)
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, len(rows) * (th + 50) + 10), (8, 8, 8))
    d = ImageDraw.Draw(sheet)
    for r, (pose, paths) in enumerate(rows):
        y0 = 10 + r * (th + 50)
        d.text((10, y0), pose, font=font(18), fill=(255, 255, 255))
        for c, path in enumerate(paths):
            frame = stage.copy()
            body = Image.open(path).convert("RGBA")
            frame.paste(body, (round(feet[0] - body.width / 2), round(feet[1] - body.height)), body)
            x0 = 10 + c * (tw + 10)
            sheet.paste(frame.resize(THUMB), (x0, y0 + 30))
            d.text(
                (x0 + 4, y0 + 34), path.stem.rsplit("-", 1)[1], font=font(18), fill=(255, 210, 31)
            )
    return sheet


def seed(key: str, take: int) -> int:
    return zlib.crc32(key.encode()) % 100_000 * 100 + take


async def paint_all(args: argparse.Namespace, library: Library, art: dict[str, str]) -> None:
    look = tomllib.loads((ROOT / "styles" / f"{args.style}.toml").read_text(encoding="utf-8"))
    frame = look["look"]["frame"]
    workflow = Workflow.load(ROOT / "workflows" / "keyframe.json")
    out = args.series / "art"
    async with httpx.AsyncClient(base_url=args.comfy) as http:
        client = ComfyClient(http)
        if args.only in (None, "locations"):
            painter = ComfyPainter(
                client, workflow, width=PAINT[0], height=PAINT[1], steps=args.steps
            )
            (out / "locations").mkdir(parents=True, exist_ok=True)
            takes: dict[str, list[Path]] = {}
            for key, location in library.locations.items():
                prompt = location_prompt(location, frame)
                for n in range(1, args.takes + 1):
                    path = out / "locations" / f"{key}-{n}.png"
                    await painter.paint(prompt, seed=seed(key, n), out=path)
                    picture = Image.open(path).convert("RGB")
                    left = (picture.width - W) // 2
                    picture.crop((left, 0, left + W, H)).save(path)
                    takes.setdefault(key, []).append(path)
                    print(path)
                (out / "locations" / f"{key}.txt").write_text(prompt + "\n", encoding="utf-8")
            location_sheet(takes, library).save(out / "locations.jpg", quality=88)
            print(out / "locations.jpg")
        if args.only in (None, "poses"):
            painter = ComfyPainter(
                client, workflow, width=FIGURE[0], height=FIGURE[1], steps=args.steps
            )
            (out / "poses").mkdir(parents=True, exist_ok=True)
            who = art.get("hero", "a person")
            takes = {}
            for pose, about in library.poses.items():
                prompt = pose_prompt(about, who, frame)
                for n in range(1, args.takes + 1):
                    raw = out / "poses" / f"{pose}-{n}.raw.png"
                    await painter.paint(prompt, seed=seed(pose, n), out=raw)
                    path = raw.with_name(f"{pose}-{n}.png")
                    figure(Image.open(raw)).save(path)
                    takes.setdefault(pose, []).append(path)
                    print(path)
            pose_sheet(takes, library, args.series).save(out / "poses.jpg", quality=88)
            print(out / "poses.jpg")


def pick(series: Path, library: Library, choices: list[str]) -> None:
    for choice in choices:
        key, _, take = choice.partition("=")
        kind = (
            "locations" if key in library.locations else "poses" if key in library.poses else None
        )
        if kind is None or not take.isdigit():
            raise SystemExit(f"{choice}: expected <location or pose>=<take number>")
        source = series / "art" / kind / f"{key}-{take}.png"
        if not source.exists():
            raise SystemExit(f"{source}: no such take")
        (series / kind).mkdir(exist_ok=True)
        shutil.copyfile(source, series / kind / f"{key}.png")
        print(series / kind / f"{key}.png")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("series", type=Path)
    parser.add_argument("--takes", type=int, default=4)
    parser.add_argument("--only", choices=("locations", "poses"))
    parser.add_argument("--style", default="rules-beats")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--comfy", default="http://localhost:8188")
    parser.add_argument("--pick", nargs="+", metavar="KEY=TAKE")
    args = parser.parse_args()
    library = read_library(args.series)
    if args.pick:
        pick(args.series, library, args.pick)
        return
    raw = tomllib.loads((args.series / "library.toml").read_text(encoding="utf-8"))
    asyncio.run(paint_all(args, library, raw.get("art", {})))


if __name__ == "__main__":
    main()
