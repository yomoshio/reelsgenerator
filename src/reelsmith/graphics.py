"""Pictures drawn by code: the scene of a location, the hero as a small figure in a pose,
and every kind of graphic a beat brings up. Text is set in the channel's font, so it is
always readable, and the same script always draws the same frames.

A location or a pose drawn once by hand or by an image model, as a PNG in the series
folder, replaces the stand-in drawn here: `locations/<key>.png` at 1080x1920 and
`poses/<key>.png` with the feet at the middle of the bottom edge."""

import math
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reelsmith.beats import Anchor, Location, Reveal
from reelsmith.models import StageError

W, H = 1080, 1920
SCENE_TOP, SCENE_BOTTOM = 180, 1150  # the scene owns this band; captions live below it
HERO_HEIGHT = 380  # 19.8% of the frame, the top of the spec's 8 to 20%; the reference's is larger
SKY, GROUND = (22, 28, 40), (11, 15, 23)
LIGHT = (52, 64, 86)
STEEL, STEEL_LIT = (112, 121, 133), (198, 205, 212)
WALL_LINE = (40, 50, 68)
CARD, CARD_INK, NUMBER = (233, 223, 196), (26, 26, 26), (179, 38, 30)
WHITE = (255, 255, 255)
TONES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "neutral": ((236, 232, 222), CARD_INK),
    "threat": ((200, 56, 45), WHITE),
    "key": ((242, 194, 48), CARD_INK),
    "solved": ((46, 158, 91), WHITE),
}
WRAPS = [(64, 86, 122), (138, 74, 58), (104, 112, 66)]
CLOTHES, TROUSERS, SKIN, HAIR = (47, 58, 82), (27, 33, 48), (196, 160, 134), (24, 24, 28)
FONT = "Montserrat:style=ExtraBold"
FALLBACK = "DejaVu Sans:style=Bold"

Entrance = Literal["pop", "stamp", "draw", "fade", "cut"]
Point = tuple[float, float]


@dataclass
class Sprite:
    """A graphic placed on the frame: `image` with its top-left corner at `xy`. It comes
    in with `entrance` over `lasts` seconds from `start`, and is gone at `end`."""

    image: Image.Image
    xy: tuple[int, int]
    start: float
    end: float = math.inf
    entrance: Entrance = "pop"
    lasts: float = 0.2
    axis: Literal["x", "y"] = "x"
    kind: str = ""
    keep: bool = False


@cache
def font(size: int, family: str = FONT) -> ImageFont.FreeTypeFont:
    """The channel's font as fontconfig finds it, here and in the worker image."""
    for name in (family, FALLBACK):
        try:
            path = subprocess.run(
                ["fc-match", "-f", "%{file}", name], capture_output=True, text=True, check=True
            ).stdout.strip()
            return ImageFont.truetype(path, size)
        except (OSError, subprocess.CalledProcessError):
            continue
    raise StageError(f"no font for {family!r} or {FALLBACK!r}: install fonts-montserrat")


def at(anchor: Anchor) -> Point:
    return anchor.x * W, anchor.y * H


# --- the scene ---------------------------------------------------------------------------


def scene(key: str, location: Location, folder: Path | None = None) -> Image.Image:
    """The location as a 1080x1920 RGBA picture: its PNG if the series has one, otherwise
    a dark flat stand-in with the anchors that have a known shape drawn in."""
    if folder is not None and (path := folder / "locations" / f"{key}.png").exists():
        return Image.open(path).convert("RGBA").resize((W, H))
    floor = at(location.anchors["hero"])[1]
    img = _gradient(SKY, GROUND, H)
    _light(img, at(location.anchors["hero"])[0] + 140)
    d = ImageDraw.Draw(img)
    d.rectangle((0, floor, W, SCENE_BOTTOM), fill=(15, 20, 30))
    d.line((0, floor, W, floor), fill=WALL_LINE, width=3)
    for name, anchor in location.anchors.items():
        _object(d, name, at(anchor), floor)
    shade = _gradient((0, 0, 0, 0), (4, 6, 10, 255), H - SCENE_BOTTOM + 200, alpha=True)
    img.alpha_composite(shade, (0, SCENE_BOTTOM - 200))
    return img


def _gradient(
    top: tuple[int, ...], bottom: tuple[int, ...], height: int, *, alpha: bool = False
) -> Image.Image:
    mode = "RGBA" if alpha else "RGB"
    column = Image.new(mode, (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        column.putpixel(
            (0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        )
    return column.resize((W, height)).convert("RGBA")


def _light(img: Image.Image, x: float) -> None:
    """One soft column of light from above, the only light in the scene."""
    mask = Image.new("L", (W, H))
    ImageDraw.Draw(mask).polygon(
        [(x - 90, 0), (x + 90, 0), (x + 260, SCENE_BOTTOM), (x - 260, SCENE_BOTTOM)], fill=120
    )
    mask = mask.filter(ImageFilter.GaussianBlur(90))
    img.paste(Image.new("RGBA", (W, H), (*LIGHT, 255)), (0, 0), mask)


def _object(d: ImageDraw.ImageDraw, name: str, xy: Point, floor: float) -> None:
    x, y = xy
    if name in ("pipe", "riser"):
        d.rectangle((x - 18, 0, x + 18, floor + 6), fill=STEEL)
        d.rectangle((x - 2, 0, x + 12, floor + 6), fill=STEEL_LIT)
        d.rectangle((x - 24, floor - 4, x + 24, floor + 6), fill=(80, 88, 100))
    elif name == "door":
        d.rectangle(
            (x - 115, floor - 470, x + 115, floor), fill=(29, 37, 51), outline=WALL_LINE, width=6
        )
        d.ellipse((x + 70, floor - 250, x + 88, floor - 232), fill=(138, 147, 160))
    elif name == "window":
        d.rectangle(
            (x - 160, y - 190, x + 160, y + 190), fill=(31, 53, 80), outline=WALL_LINE, width=10
        )
        d.line((x, y - 190, x, y + 190), fill=WALL_LINE, width=8)
        d.line((x - 160, y, x + 160, y), fill=WALL_LINE, width=8)
    elif name == "railing":
        d.line((x - 260, y - 60, x + 200, y + 120), fill=STEEL, width=10)
        for i in range(6):
            bx = x - 230 + i * 80
            by = y - 48 + i * 31
            d.line((bx, by, bx, by + 170), fill=(70, 78, 92), width=6)
    elif name == "stairs_down":
        for i in range(6):
            top = floor + i * 26
            d.rectangle(
                (x - 140 + i * 50, top, x + 220, top + 26),
                fill=(20 - i * 2, 26 - i * 2, 38 - i * 3),
            )
    elif name == "table":
        d.rectangle((x - 140, y - 10, x + 140, y + 10), fill=(58, 66, 82))
        d.line((x - 120, y, x - 120, floor), fill=(58, 66, 82), width=10)
        d.line((x + 120, y, x + 120, floor), fill=(58, 66, 82), width=10)
    elif name.startswith("floor_"):
        d.rectangle((0, y - 12, W, y + 12), fill=(39, 48, 65))


# --- the hero ----------------------------------------------------------------------------

# Joints in units of the figure's height, from the feet up: x to the right, y upward.
_STAND = {
    "head": (0.0, 0.9), "neck": (0.0, 0.8), "hip": (0.0, 0.47),
    "hand_l": (-0.13, 0.46), "hand_r": (0.13, 0.46), "foot_l": (-0.06, 0.0), "foot_r": (0.06, 0.0),
}  # fmt: skip
POSES: dict[str, dict[str, Point]] = {
    "stand": {},
    "listen": {"head": (0.035, 0.885), "hand_r": (0.09, 0.84)},
    "knock": {"hand_r": (0.24, 0.8)},
    "look_down": {"head": (0.025, 0.855), "hand_l": (-0.08, 0.5), "hand_r": (0.08, 0.5)},
    "walk": {
        "foot_l": (-0.14, 0.0), "foot_r": (0.14, 0.0),
        "hand_l": (-0.18, 0.5), "hand_r": (0.16, 0.5),
    },
    "sit": {
        "head": (0.0, 0.58), "neck": (0.0, 0.48), "hip": (0.0, 0.14),
        "hand_l": (0.14, 0.26), "hand_r": (0.18, 0.26), "foot_l": (0.2, 0.0), "foot_r": (0.26, 0.0),
    },
    "hold_item": {"hand_l": (0.05, 0.6), "hand_r": (0.11, 0.6)},
}  # fmt: skip


def hero(pose: str, anchors: dict[str, Anchor], folder: Path | None = None) -> Sprite:
    """The hero standing on the location's `hero` anchor. A pose named `hand_on_<anchor>`
    reaches for that anchor; a pose without a drawing of its own stands."""
    feet = at(anchors["hero"])
    if folder is not None and (path := folder / "poses" / f"{pose}.png").exists():
        img = Image.open(path).convert("RGBA")
        return Sprite(
            img, (round(feet[0] - img.width / 2), round(feet[1] - img.height)), 0, entrance="cut"
        )
    joints = {**_STAND, **POSES.get(pose, {})}
    if pose.startswith("hand_on_") and (target := anchors.get(pose.removeprefix("hand_on_"))):
        reach = (at(target)[0] - feet[0]) / HERO_HEIGHT
        side = "hand_r" if reach >= 0 else "hand_l"
        joints[side] = (max(-0.42, min(0.42, reach - math.copysign(0.02, reach))), 0.64)
    return Sprite(
        _figure(joints),
        (round(feet[0] - HERO_HEIGHT), round(feet[1] - HERO_HEIGHT)),
        0,
        entrance="cut",
    )


def _figure(joints: dict[str, Point]) -> Image.Image:
    """The figure drawn at twice the size and shrunk, so its edges are smooth."""
    s = 2 * HERO_HEIGHT
    img = Image.new("RGBA", (2 * s, s + 20))
    d = ImageDraw.Draw(img)

    def p(name: str) -> Point:
        x, y = joints[name]
        return s + x * s, s - y * s

    limb = round(0.06 * s)
    shoulder = p("neck")[0], p("neck")[1] + 0.03 * s
    hip = p("hip")
    for foot in ("foot_l", "foot_r"):
        _limb(d, (hip[0], hip[1] - 0.02 * s), p(foot), limb, TROUSERS)
    _limb(d, shoulder, p("hand_l"), round(limb * 0.85), CLOTHES)
    d.polygon(
        [
            (shoulder[0] - 0.1 * s, shoulder[1]),
            (shoulder[0] + 0.1 * s, shoulder[1]),
            (hip[0] + 0.085 * s, hip[1]),
            (hip[0] - 0.085 * s, hip[1]),
        ],
        fill=CLOTHES,
    )
    _limb(d, shoulder, p("hand_r"), round(limb * 0.85), CLOTHES)
    for hand in ("hand_l", "hand_r"):
        x, y = p(hand)
        d.ellipse((x - limb * 0.45, y - limb * 0.45, x + limb * 0.45, y + limb * 0.45), fill=SKIN)
    hx, hy = p("head")
    r = 0.075 * s
    d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=SKIN)
    d.chord((hx - r, hy - r, hx + r, hy + r * 0.7), 180, 360, fill=HAIR)
    return img.resize((img.width // 2, img.height // 2), Image.Resampling.LANCZOS)


def _limb(
    d: ImageDraw.ImageDraw, a: Point, b: Point, width: int, colour: tuple[int, int, int]
) -> None:
    d.line((a, b), fill=colour, width=width)
    for x, y in (a, b):
        d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=colour)


# --- graphics ----------------------------------------------------------------------------


def rule_card(text: str, start: float) -> Sprite:
    """The numbered rule at the top, beige with the number in red, tilted a little."""
    number, _, rest = text.partition(" ")
    big, small = font(66), font(48)
    w = round(small.getlength(number + " ") + big.getlength(rest.upper())) + 64
    card = Image.new("RGBA", (w, 112))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, 111), radius=6, fill=CARD)
    d.text((32, 62), number, font=small, fill=NUMBER, anchor="ls")
    d.text(
        (32 + small.getlength(number + " "), 80), rest.upper(), font=big, fill=CARD_INK, anchor="ls"
    )
    card = _shadowed(card).rotate(2.5, expand=True, resample=Image.Resampling.BICUBIC)
    return Sprite(card, (round(W / 2 - card.width / 2), 40), start)


def hud(text: str, start: float) -> Sprite:
    """Day and time in a thin strip at the top left."""
    f = font(40)
    w = round(f.getlength(text.upper())) + 56
    strip = Image.new("RGBA", (w, 64))
    d = ImageDraw.Draw(strip)
    d.rectangle((0, 0, w - 1, 63), fill=(8, 10, 16, 200))
    d.rectangle((0, 0, 7, 63), fill=TONES["key"][0])
    d.text((30, 32), text.upper(), font=f, fill=WHITE, anchor="lm")
    return Sprite(strip, (36, 196), start, entrance="fade")


def plate(text: str, tone: str, size: int = 40) -> Image.Image:
    fill, ink = TONES.get(tone, TONES["neutral"])
    f = font(size)
    w = round(f.getlength(text.upper())) + 2 * size
    h = round(size * 1.75)
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=fill)
    d.text((w / 2, h / 2), text.upper(), font=f, fill=ink, anchor="mm")
    return _shadowed(img)


def label(text: str, tone: str, target: Point, start: float, row: int = 0) -> list[Sprite]:
    """A plate above the thing it names, joined to it by a line that draws itself."""
    x, y = target
    img = plate(text, tone)
    top = max(SCENE_TOP + 30, y - 220 - row * 100)
    left = round(min(max(x - img.width / 2, 24), W - img.width - 24))
    line = Image.new("RGBA", (6, max(round(y - top - img.height / 2), 6)))
    ImageDraw.Draw(line).rectangle(
        (0, 0, 5, line.height), fill=(*TONES.get(tone, TONES["neutral"])[0], 220)
    )
    return [
        Sprite(
            line,
            (round(x - 3), round(top + img.height / 2)),
            start,
            entrance="draw",
            axis="y",
            lasts=0.15,
        ),
        Sprite(img, (left, round(top)), start + 0.08),
    ]


def status(text: str, tone: str, target: Point, start: float) -> Sprite:
    """A coloured plate with a short state, under the thing it is about or above it when
    there is no room below, and a bar the width of the plate in the same colour."""
    img = plate(text, tone, size=30)
    canvas = Image.new("RGBA", (img.width, img.height + 22))
    canvas.alpha_composite(img)
    ImageDraw.Draw(canvas).rounded_rectangle(
        (8, img.height + 6, img.width - 8, img.height + 16), radius=5, fill=TONES[tone][0]
    )
    x, y = target
    top = y + 8 if y + 8 + canvas.height <= SCENE_BOTTOM else y - canvas.height - 8
    left = min(max(x - canvas.width / 2, 24), W - canvas.width - 24)
    return Sprite(canvas, (round(left), round(top)), start)


def stamp(text: str, start: float) -> Sprite:
    """A red stamp across the middle of the scene that lands with a shake."""
    f = font(104)
    w = round(f.getlength(text.upper())) + 90
    img = Image.new("RGBA", (w, 170))
    d = ImageDraw.Draw(img)
    red = (*TONES["threat"][0], 235)
    d.rounded_rectangle((6, 6, w - 7, 163), radius=14, outline=red, width=12)
    d.text((w / 2, 88), text.upper(), font=f, fill=red, anchor="mm")
    img = img.rotate(-9, expand=True, resample=Image.Resampling.BICUBIC)
    return Sprite(
        img,
        (round(W / 2 - img.width / 2), round((SCENE_TOP + SCENE_BOTTOM) / 2 - img.height / 2)),
        start,
        entrance="stamp",
        lasts=0.25,
    )


def lens(base: Image.Image, target: Point, start: float, text: str = "") -> list[Sprite]:
    """A circle that shows the target twice as large, beside it, with a line to it."""
    x, y = target
    r = 170
    crop = base.crop(
        (round(x - r / 2), round(y - r / 2), round(x + r / 2), round(y + r / 2))
    ).resize((2 * r, 2 * r))
    disc = Image.new("RGBA", (2 * r + 16, 2 * r + 16))
    mask = Image.new("L", (2 * r, 2 * r))
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
    disc.paste(crop, (8, 8), mask)
    ImageDraw.Draw(disc).ellipse((2, 2, 2 * r + 13, 2 * r + 13), outline=WHITE, width=8)
    cx = x + (r + 90 if x < W / 2 else -(r + 90))
    cy = max(SCENE_TOP + r + 20, y - r - 60)
    sprites = [Sprite(disc, (round(cx - r - 8), round(cy - r - 8)), start)]
    if text:
        tag = plate(text, "key", size=34)
        sprites.append(Sprite(tag, (round(cx - tag.width / 2), round(cy + r + 4)), start + 0.1))
    return sprites


def diagram_step(text: str, tone: str, origin: Point, target: Point, start: float) -> list[Sprite]:
    """A dashed line that draws itself from the last step to the target, ending in a dot
    and a plate."""
    (x0, y0), (x1, y1) = origin, target
    left, top = min(x0, x1) - 12, min(y0, y1) - 12
    img = Image.new("RGBA", (round(abs(x1 - x0)) + 24, round(abs(y1 - y0)) + 24))
    d = ImageDraw.Draw(img)
    colour = TONES.get(tone, TONES["key"])[0] if tone != "neutral" else TONES["key"][0]
    steps = max(round(math.dist(origin, target) / 28), 1)
    for i in range(0, steps, 2):
        a = i / steps
        b = min((i + 1) / steps, 1)
        d.line(
            (
                (x0 - left + (x1 - x0) * a, y0 - top + (y1 - y0) * a),
                (x0 - left + (x1 - x0) * b, y0 - top + (y1 - y0) * b),
            ),
            fill=colour,
            width=8,
        )
    d.ellipse((x1 - left - 12, y1 - top - 12, x1 - left + 12, y1 - top + 12), fill=colour)
    axis: Literal["x", "y"] = "x" if abs(x1 - x0) >= abs(y1 - y0) else "y"
    sprites = [Sprite(img, (round(left), round(top)), start, entrance="draw", axis=axis, lasts=0.3)]
    if text:
        tag = plate(text, tone if tone != "neutral" else "key", size=34)
        sprites.append(
            Sprite(
                tag,
                (
                    round(min(max(x1 - tag.width / 2, 24), W - tag.width - 24)),
                    round(y1 - tag.height - 24),
                ),
                start + 0.25,
            )
        )
    return sprites


BANDS = 3  # bands a prop gains at each stage
BAND = 70


def wrap(x: float, floor: float, stage: int, stages: int, start: float) -> list[Sprite]:
    """One more stage of a prop: bands wrapped round it one after another, stacked up from
    the floor over the bands of earlier stages, and at the last stage tape across them."""
    sprites = []
    for j in range(BANDS):
        n = (stage - 1) * BANDS + j
        colour = WRAPS[n % len(WRAPS)]
        img = Image.new("RGBA", (124, BAND + 8))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((4, 4, 119, BAND + 3), radius=18, fill=colour)
        light = tuple(min(c + 50, 255) for c in colour)
        d.line((16, BAND // 2 + 4, 108, BAND // 2 + 4), fill=light, width=6)
        top = floor + 4 - (BAND + 8) - n * (BAND - 6)
        sprites.append(Sprite(img, (round(x - 62), round(top)), start + 0.12 * j, lasts=0.16))
    if stage >= stages - 1 and stages > 2:
        tall = stage * BANDS * (BAND - 6) + 6
        tape = Image.new("RGBA", (132, tall))
        d = ImageDraw.Draw(tape)
        for ty in range(10, tall - 10, BAND - 6):
            d.rectangle((0, ty, 131, ty + 10), fill=(178, 180, 174, 235))
        sprites.append(
            Sprite(
                tape,
                (round(x - 66), round(floor - tall)),
                start + 0.12 * BANDS,
                entrance="draw",
                axis="y",
            )
        )
    return sprites


def _shadowed(img: Image.Image) -> Image.Image:
    out = Image.new("RGBA", (img.width + 16, img.height + 16))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.putalpha(img.getchannel("A").point(lambda a: a * 0.5))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5)), (8, 10))
    out.alpha_composite(img, (4, 2))
    return out


# --- one frame ---------------------------------------------------------------------------


def state(sprite: Sprite, t: float, fps: int) -> int | None:
    """Which frame of its entrance the sprite shows at `t`: None before it starts or after
    it ends, -1 once it has fully come in."""
    if t < sprite.start or t >= sprite.end:
        return None
    if sprite.entrance == "cut" or t >= sprite.start + sprite.lasts:
        return -1
    return int((t - sprite.start) * fps)


def drawn(sprite: Sprite, t: float) -> tuple[Image.Image, tuple[int, int]]:
    """The sprite as it looks `t` seconds into the beat."""
    p = min(max((t - sprite.start) / sprite.lasts, 0.0), 1.0) if sprite.lasts else 1.0
    img, (x, y) = sprite.image, sprite.xy
    if p >= 1 or sprite.entrance == "cut":
        return img, (x, y)
    if sprite.entrance == "fade":
        return _faded(img, p), (x, y)
    if sprite.entrance == "draw":
        if sprite.axis == "x":
            return img.crop((0, 0, max(round(img.width * p), 1), img.height)), (x, y)
        return img.crop((0, 0, img.width, max(round(img.height * p), 1))), (x, y)
    if sprite.entrance == "stamp":
        scale = 1.6 - 0.6 * min(p / 0.6, 1)
        shake = round(6 * math.sin(p * 40)) if p > 0.6 else 0
        alpha = min(p / 0.3, 1)
    else:
        scale = 0.7 + 0.4 * (p / 0.45) if p < 0.45 else 1.1 - 0.1 * (p - 0.45) / 0.55
        shake, alpha = 0, min(p / 0.35, 1)
    size = max(round(img.width * scale), 1), max(round(img.height * scale), 1)
    scaled = _faded(img.resize(size, Image.Resampling.BILINEAR), alpha)
    cx, cy = x + img.width / 2, y + img.height / 2
    return scaled, (round(cx - size[0] / 2) + shake, round(cy - size[1] / 2))


def _faded(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 1:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda a: round(a * alpha)))
    return out


def compose(base: Image.Image, sprites: list[Sprite], t: float) -> Image.Image:
    frame = base.copy()
    for sprite in sprites:
        if t < sprite.start or t >= sprite.end:
            continue
        img, (x, y) = drawn(sprite, t)
        frame.alpha_composite(img, (max(x, 0), max(y, 0)), (max(-x, 0), max(-y, 0)))
    return frame


def reveal_sprites(
    reveal: Reveal,
    *,
    start: float,
    location: Location,
    base: Image.Image,
    rows: dict[str, int],
    stage: int,
    stages: int,
    origin: Point,
) -> list[Sprite]:
    """The sprites one reveal brings up. `rows` counts plates already pinned above each
    anchor, so a second label on the same thing sits above the first."""
    target = at(location.anchors[reveal.target]) if reveal.target in location.anchors else None
    hero_at = at(location.anchors["hero"])
    point = target or hero_at
    made: list[Sprite] = []
    match reveal.kind:
        case "rule_card":
            made = [rule_card(reveal.text, start)]
        case "hud":
            made = [hud(reveal.text, start)]
        case "stamp":
            made = [stamp(reveal.text, start)]
        case "label":
            row = rows.get(reveal.target, 0)
            rows[reveal.target] = row + 1
            above = HERO_HEIGHT if target is None or reveal.target == "hero" else 0
            made = label(reveal.text, reveal.style, (point[0], point[1] - above), start, row)
        case "status":
            made = [status(reveal.text, reveal.style, point, start)]
        case "lens":
            made = lens(base, point, start, reveal.text)
        case "diagram_step":
            made = diagram_step(reveal.text, reveal.style, origin, point, start)
        case "prop_stage" if target is not None and stage > 0:
            made = wrap(target[0], hero_at[1], stage, stages, start)
    return made
